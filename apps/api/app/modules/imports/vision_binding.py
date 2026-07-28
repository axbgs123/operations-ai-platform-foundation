from dataclasses import dataclass
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.imports.ocr_adapters import MockVisionAdapter, VisionAdapter
from app.modules.metrics.definitions import get_metric_definitions
from app.modules.metrics.models import ContentType, MetricDefinition
from app.modules.models.adapters.qianwen_vision import QianwenVisionAdapter
from app.modules.models.capabilities import Capability
from app.modules.models.catalog import QianwenRegion, get_catalog_entry
from app.modules.models.config_service import ModelConfigService, SecretCipher
from app.modules.models.models import ModelConfig, ModelConfigStatus


@dataclass(frozen=True)
class VisionBinding:
    model_config_id: UUID | None
    provider: str
    model_id: str
    contract_version: str
    config_version: str
    region: str | None
    metric_labels: dict[str, str]


def metric_labels(
    session: Session,
    *,
    workspace_id: UUID,
    platform: Platform,
    content_type: ContentType,
) -> dict[str, str]:
    labels = {
        item.label: item.key
        for item in get_metric_definitions(platform, content_type)
    }
    custom = session.scalars(
        select(MetricDefinition).where(
            MetricDefinition.workspace_id == workspace_id,
            MetricDefinition.platform == platform,
            MetricDefinition.content_type == content_type,
        )
    )
    for item in custom:
        labels[item.label] = item.key
    return dict(sorted(labels.items()))


def resolve_vision_binding(
    session: Session,
    context: WorkspaceContext,
    *,
    platform: Platform,
    content_type: ContentType,
    cipher: SecretCipher,
    mock_mode: bool,
) -> VisionBinding:
    labels = metric_labels(
        session,
        workspace_id=context.workspace_id,
        platform=platform,
        content_type=content_type,
    )
    if mock_mode:
        return VisionBinding(
            model_config_id=None,
            provider="mock",
            model_id="mock-vision-v1",
            contract_version="mock-vision-v1",
            config_version="mock-static-v1",
            region=None,
            metric_labels=labels,
        )
    config = ModelConfigService(
        session, context, cipher=cipher
    ).resolve({Capability.VISION}, provider="qianwen")
    catalog = get_catalog_entry(config.provider, config.model_id)
    return VisionBinding(
        model_config_id=config.id,
        provider=config.provider,
        model_id=config.model_id,
        contract_version=catalog.contract_version,
        config_version=config.updated_at.isoformat(),
        region=config.region,
        metric_labels=labels,
    )


def create_bound_vision_adapter(
    session: Session,
    *,
    workspace_id: UUID,
    expected_platform: Platform,
    binding: VisionBinding,
    cipher: SecretCipher,
    mock_mode: bool,
    transport: httpx.BaseTransport | None = None,
) -> VisionAdapter:
    if binding.provider == "mock":
        if not mock_mode or binding.model_id != "mock-vision-v1":
            raise ValueError("frozen vision configuration is unavailable")
        return MockVisionAdapter(expected_platform)
    if binding.model_config_id is None:
        raise ValueError("frozen vision configuration is unavailable")
    config = session.scalar(
        select(ModelConfig).where(
            ModelConfig.id == binding.model_config_id,
            ModelConfig.workspace_id == workspace_id,
        )
    )
    if (
        config is None
        or config.status is ModelConfigStatus.INCOMPATIBLE
        or config.provider != binding.provider
        or config.model_id != binding.model_id
        or config.updated_at.isoformat() != binding.config_version
        or config.region is None
        or config.provider_workspace_id is None
        or Capability.VISION.value not in config.capabilities
    ):
        raise ValueError("frozen vision configuration is unavailable")
    catalog = get_catalog_entry(config.provider, config.model_id)
    if catalog.contract_version != binding.contract_version:
        raise ValueError("frozen vision configuration is unavailable")
    return QianwenVisionAdapter(
        workspace_id=workspace_id,
        model_config_id=config.id,
        expected_platform=expected_platform,
        region=QianwenRegion(config.region),
        provider_workspace_id=config.provider_workspace_id,
        api_key=SecretStr(cipher.decrypt(config.encrypted_api_key)),
        model_id=config.model_id,
        contract_version=binding.contract_version,
        allowed_metric_labels=binding.metric_labels,
        transport=transport,
    )
