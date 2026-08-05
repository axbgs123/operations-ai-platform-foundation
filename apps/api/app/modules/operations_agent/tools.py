from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.operations_agent.models import AgentToolRisk
from app.modules.workspace.permissions import Permission


class AgentToolInputError(ValueError):
    pass


class AgentToolOutputError(ValueError):
    pass


class AgentToolContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    name: str
    version: str
    risk: AgentToolRisk
    permission: Permission
    uses_external_api: bool
    retry_policy: Literal["safe", "never", "manual"]
    input_model: type[BaseModel]
    output_model: type[BaseModel]


class AgentToolRegistry:
    def __init__(
        self,
        contracts: Iterable[AgentToolContract],
        *,
        catalog_version: str = "agent-tools-v1",
    ) -> None:
        self.catalog_version = catalog_version
        registered: dict[tuple[str, str], AgentToolContract] = {}
        versions_by_name: dict[str, list[str]] = {}
        for contract in contracts:
            key = (contract.name, contract.version)
            if key in registered:
                raise ValueError(
                    "duplicate agent tool contract "
                    f"{contract.name} {contract.version}"
                )
            registered[key] = contract
            versions_by_name.setdefault(contract.name, []).append(
                contract.version
            )
        self._contracts: Mapping[
            tuple[str, str], AgentToolContract
        ] = registered
        self._versions_by_name = {
            name: tuple(sorted(versions))
            for name, versions in versions_by_name.items()
        }

    def contracts(self) -> tuple[AgentToolContract, ...]:
        """Return the immutable public catalog in deterministic order."""
        return tuple(
            self._contracts[key]
            for key in sorted(self._contracts)
        )

    def get(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> AgentToolContract:
        versions = self._versions_by_name.get(name, ())
        if version is None:
            if len(versions) != 1:
                raise AgentToolInputError(
                    f"agent tool {name!r} requires an explicit version"
                )
            version = versions[0]
        try:
            return self._contracts[(name, version)]
        except KeyError as error:
            raise AgentToolInputError(
                f"unknown agent tool {name!r} version {version!r}"
            ) from error

    def validate_call(
        self,
        name: str,
        arguments: object,
        *,
        version: str | None = None,
    ) -> BaseModel:
        contract = self.get(name, version=version)
        try:
            return contract.input_model.model_validate(arguments)
        except ValidationError as error:
            raise AgentToolInputError(
                f"invalid arguments for agent tool {name!r}"
            ) from error

    def validate_result(
        self,
        name: str,
        result: object,
        *,
        version: str | None = None,
    ) -> BaseModel:
        contract = self.get(name, version=version)
        try:
            return contract.output_model.model_validate(result)
        except ValidationError as error:
            raise AgentToolOutputError(
                f"invalid result for agent tool {name!r}"
            ) from error
