from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.models.adapters.mock import MockProvider
from app.modules.models.adapters.qianwen import QianwenProvider
from app.modules.models.capabilities import Capability
from app.modules.models.catalog import (
    QianwenRegion,
    get_catalog_entry,
)
from app.modules.models.config_service import SecretCipher
from app.modules.models.models import ModelConfig, ModelConfigStatus


@dataclass(frozen=True)
class ModelBinding:
    provider: str
    model_id: str
    contract_version: str
    configuration_version: str | None = None


@dataclass(frozen=True)
class BoundModelAdapter:
    adapter: MockProvider | QianwenProvider
    binding: ModelBinding


class ModelSelectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def create_workspace_model_adapter(
    *,
    session: Session,
    workspace_id: UUID,
    model_config_id: UUID,
    required_capability: Capability,
    cipher: SecretCipher,
    mock_mode: bool,
    expected: ModelBinding,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BoundModelAdapter:
    if mock_mode:
        binding = ModelBinding(
            provider="mock",
            model_id="mock-v1",
            contract_version="mock-structured-v1",
        )
        if expected != binding:
            raise ModelSelectionError(
                "MODEL_CONFIGURATION_REQUIRED",
                "模型配置不可用，请重新创建任务。",
            )
        return BoundModelAdapter(
            adapter=MockProvider(
                capabilities=frozenset({required_capability})
            ),
            binding=binding,
        )

    config = session.scalar(
        select(ModelConfig).where(
            ModelConfig.id == model_config_id,
            ModelConfig.workspace_id == workspace_id,
        )
    )
    if config is None:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型配置不可用，请重新创建任务。",
        )
    if config.status is ModelConfigStatus.INCOMPATIBLE:
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定模型配置当前不可用。",
        )
    if config.provider != "qianwen":
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定模型 Provider 不受支持。",
        )
    try:
        catalog = get_catalog_entry(config.provider, config.model_id)
    except LookupError as error:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型配置不可用，请重新创建任务。",
        ) from error
    binding = ModelBinding(
        provider=config.provider,
        model_id=config.model_id,
        contract_version=catalog.contract_version,
        configuration_version=config.updated_at.isoformat(),
    )
    if binding != expected:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型配置不可用，请重新创建任务。",
        )
    if (
        required_capability not in catalog.capabilities
        or required_capability.value not in config.capabilities
        or config.status.value != catalog.adapter_status.value
    ):
        raise ModelSelectionError(
            "MODEL_CAPABILITY_UNAVAILABLE",
            "固定模型能力当前不可用。",
        )
    if config.region is None or config.provider_workspace_id is None:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型配置不可用，请重新创建任务。",
        )
    if config.encryption_key_version != cipher.version:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型密钥版本不可用，请重新配置。",
        )
    try:
        api_key = SecretStr(cipher.decrypt(config.encrypted_api_key))
        region = QianwenRegion(config.region)
        adapter = QianwenProvider(
            api_key=api_key,
            region=region,
            provider_workspace_id=config.provider_workspace_id,
            model_id=config.model_id,
            transport=transport,
        )
    except ValueError as error:
        raise ModelSelectionError(
            "MODEL_CONFIGURATION_REQUIRED",
            "模型配置不可用，请重新创建任务。",
        ) from error
    return BoundModelAdapter(adapter=adapter, binding=binding)
