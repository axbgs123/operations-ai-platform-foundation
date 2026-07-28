from collections.abc import Iterable
import base64
import hashlib
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    ModelDescriptor,
    select_compatible_model,
)
from app.modules.models.catalog import (
    QianwenRegion,
    get_catalog_entry,
    validate_provider_workspace_id,
)
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.workspace.permissions import Permission, require_permission


class ModelConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    provider: str
    model_id: str
    region: QianwenRegion | None
    capabilities: list[Capability]
    status: AdapterStatus


class ModelConfigurationRequired(LookupError):
    code = "MODEL_CONFIGURATION_REQUIRED"
    action = "configure_model"

    def __init__(self, required_capabilities: Iterable[Capability]) -> None:
        self.required_capabilities = tuple(
            sorted(set(required_capabilities), key=lambda item: item.value)
        )
        names = ", ".join(item.value for item in self.required_capabilities)
        super().__init__(f"请联系管理员配置支持 {names} 的模型")


class SecretCipher:
    version = "v1"

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError("model secret encryption key is required")
        derived_key = hashlib.sha256(key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived_key))

    def encrypt(self, value: str) -> str:
        if not value:
            raise ValueError("model API key is required")
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as error:
            raise ValueError("model API key cannot be decrypted") from error


class ModelConfigService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        cipher: SecretCipher,
        verified_adapters: frozenset[tuple[str, str]] = frozenset(
            {("mock", "mock-v1")}
        ),
    ) -> None:
        self._session = session
        self._context = context
        self._cipher = cipher
        self._verified_adapters = verified_adapters

    def _validate_status(
        self,
        provider: str,
        model_id: str,
        status: AdapterStatus,
    ) -> None:
        if (
            status is AdapterStatus.VERIFIED
            and (provider, model_id) not in self._verified_adapters
        ):
            raise ValueError(
                "verified status requires a passing adapter contract"
            )

    def save(
        self,
        *,
        provider: str,
        model_id: str,
        capabilities: frozenset[Capability],
        status: AdapterStatus,
        api_key: str,
        region: QianwenRegion | None = None,
        provider_workspace_id: str | None = None,
    ) -> ModelConfig:
        require_permission(self._context.role, Permission.MANAGE_MODELS)
        if provider == "qianwen":
            try:
                catalog_entry = get_catalog_entry(provider, model_id)
            except LookupError as error:
                raise ValueError(
                    "model is not present in the Provider Catalog"
                ) from error
            if capabilities != catalog_entry.capabilities:
                raise ValueError("capabilities must match the Provider Catalog")
            if status is not catalog_entry.adapter_status:
                raise ValueError("status must match the Provider Catalog")
            if region is None:
                raise ValueError("Qianwen region is required")
            if region not in catalog_entry.available_regions:
                raise ValueError("unsupported Qianwen region")
            if provider_workspace_id is None:
                raise ValueError("Qianwen Provider Workspace ID is required")
            validate_provider_workspace_id(provider_workspace_id)
        else:
            if region is not None or provider_workspace_id is not None:
                raise ValueError(
                    "region and Provider Workspace ID are Qianwen-only fields"
                )
            self._validate_status(provider, model_id, status)
        capability_values = sorted(
            capability.value for capability in capabilities
        )
        encrypted_api_key = self._cipher.encrypt(api_key)
        config = self._session.scalar(
            select(ModelConfig).where(
                ModelConfig.workspace_id == self._context.workspace_id,
                ModelConfig.provider == provider,
                ModelConfig.model_id == model_id,
            )
        )
        if config is None:
            candidate = ModelConfig(
                workspace_id=self._context.workspace_id,
                provider=provider,
                model_id=model_id,
                region=region.value if region is not None else None,
                provider_workspace_id=provider_workspace_id,
                capabilities=capability_values,
                status=ModelConfigStatus(status.value),
                encrypted_api_key=encrypted_api_key,
                encryption_key_version=self._cipher.version,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(candidate)
                    self._session.flush()
            except IntegrityError:
                config = self._session.scalar(
                    select(ModelConfig).where(
                        ModelConfig.workspace_id == self._context.workspace_id,
                        ModelConfig.provider == provider,
                        ModelConfig.model_id == model_id,
                    )
                )
                if config is None:
                    raise
            else:
                config = candidate
        config.capabilities = capability_values
        config.status = ModelConfigStatus(status.value)
        config.region = region.value if region is not None else None
        config.provider_workspace_id = provider_workspace_id
        config.encrypted_api_key = encrypted_api_key
        config.encryption_key_version = self._cipher.version
        self._session.flush()
        return config

    def public(self, config: ModelConfig) -> ModelConfigRead:
        return ModelConfigRead(
            id=config.id,
            workspace_id=config.workspace_id,
            provider=config.provider,
            model_id=config.model_id,
            region=(
                QianwenRegion(config.region)
                if config.region is not None
                else None
            ),
            capabilities=[Capability(value) for value in config.capabilities],
            status=AdapterStatus(config.status.value),
        )

    def decrypt_key(self, config_id: UUID) -> SecretStr:
        require_permission(self._context.role, Permission.MANAGE_MODELS)
        config = self._session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == config_id,
                ModelConfig.workspace_id == self._context.workspace_id,
            )
        )
        if config is None:
            raise LookupError("model config not found")
        if config.encryption_key_version != self._cipher.version:
            raise ValueError("model API key uses an unsupported key version")
        return SecretStr(self._cipher.decrypt(config.encrypted_api_key))

    def list_public(self) -> list[ModelConfigRead]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        rows = self._session.scalars(
            select(ModelConfig).where(
                ModelConfig.workspace_id == self._context.workspace_id
            ).order_by(ModelConfig.provider, ModelConfig.model_id, ModelConfig.id)
        )
        return [self.public(row) for row in rows]

    def set_status(
        self,
        config_id: UUID,
        status: AdapterStatus,
    ) -> ModelConfig:
        require_permission(self._context.role, Permission.MANAGE_MODELS)
        config = self._session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == config_id,
                ModelConfig.workspace_id == self._context.workspace_id,
            )
        )
        if config is None:
            raise LookupError("model config not found")
        if config.provider == "qianwen":
            catalog_entry = get_catalog_entry(config.provider, config.model_id)
            if status not in {
                catalog_entry.adapter_status,
                AdapterStatus.INCOMPATIBLE,
            }:
                raise ValueError(
                    "status must match the Provider Catalog or be incompatible"
                )
        else:
            self._validate_status(config.provider, config.model_id, status)
        config.status = ModelConfigStatus(status.value)
        self._session.flush()
        return config

    def resolve(
        self,
        required_capabilities: Iterable[Capability],
    ) -> ModelConfig:
        required = frozenset(required_capabilities)
        require_permission(self._context.role, Permission.READ_CONTENT)
        rows = list(self._session.scalars(
            select(ModelConfig).where(
                ModelConfig.workspace_id == self._context.workspace_id,
                ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
            )
        ))
        descriptors = [
            ModelDescriptor(
                provider=row.provider,
                model_id=row.model_id,
                capabilities=frozenset(
                    Capability(value) for value in row.capabilities
                ),
                status=AdapterStatus(row.status.value),
            )
            for row in rows
        ]
        try:
            selected = select_compatible_model(descriptors, required)
        except ValueError as error:
            raise ModelConfigurationRequired(required) from error
        return next(
            row
            for row in rows
            if row.provider == selected.provider and row.model_id == selected.model_id
        )
