from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.models.capabilities import AdapterStatus, Capability


QIANWEN_TEXT_MODEL_ID: Literal["qwen3.5-plus-2026-04-20"] = (
    "qwen3.5-plus-2026-04-20"
)
QIANWEN_OCR_MODEL_ID: Literal["qwen-vl-ocr-2025-11-20"] = (
    "qwen-vl-ocr-2025-11-20"
)
QIANWEN_EMBEDDING_MODEL_ID: Literal["text-embedding-v4"] = (
    "text-embedding-v4"
)
QIANWEN_EMBEDDING_CONTRACT_VERSION = (
    "qianwen-text-embedding-v4-d1024-v1"
)
QIANWEN_EMBEDDING_DIMENSION = 1024
QIANWEN_IMAGE_MODEL_ID: Literal["qwen-image-2.0-pro-2026-06-22"] = (
    "qwen-image-2.0-pro-2026-06-22"
)
QIANWEN_IMAGE_CONTRACT_VERSION = (
    "qianwen-image-2.0-pro-2026-06-22-cover-layer-v1"
)
_PROVIDER_WORKSPACE_ID = re.compile(r"^llm-[a-z0-9]{4,64}$")


class QianwenRegion(StrEnum):
    CN_BEIJING = "cn-beijing"
    AP_SOUTHEAST_1 = "ap-southeast-1"


class ProviderProtocol(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    OPENAI_EMBEDDINGS = "openai_embeddings"
    DASHSCOPE_MULTIMODAL_GENERATION = "dashscope_multimodal_generation"


class ProviderCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["qianwen"]
    model_id: str
    capabilities: frozenset[Capability]
    protocol: ProviderProtocol
    available_regions: frozenset[QianwenRegion]
    adapter_status: Literal[AdapterStatus.EXPERIMENTAL]
    structured_output_support: bool
    thinking_mode: str
    contract_version: str
    min_pixels: int | None = None
    max_pixels: int | None = None
    max_image_bytes: int | None = None
    supported_mime_types: frozenset[str] = frozenset()
    confidence_available: bool | None = None
    max_output_tokens: int | None = None
    embedding_dimension: int | None = None
    max_batch_size: int | None = None
    max_batch_tokens_by_region: dict[QianwenRegion, int] = {}
    upstream_snapshot_immutable: bool | None = None
    max_reference_images: int | None = None
    max_output_images: int | None = None


_QIANWEN_TEXT = ProviderCatalogEntry(
    provider="qianwen",
    model_id=QIANWEN_TEXT_MODEL_ID,
    capabilities=frozenset({Capability.TEXT}),
    protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
    available_regions=frozenset(QianwenRegion),
    adapter_status=AdapterStatus.EXPERIMENTAL,
    structured_output_support=True,
    thinking_mode="disabled_for_structured_output",
    contract_version="qianwen-chat-json-v1",
)
_QIANWEN_OCR = ProviderCatalogEntry(
    provider="qianwen",
    model_id=QIANWEN_OCR_MODEL_ID,
    capabilities=frozenset({Capability.VISION}),
    protocol=ProviderProtocol.DASHSCOPE_MULTIMODAL_GENERATION,
    available_regions=frozenset(QianwenRegion),
    adapter_status=AdapterStatus.EXPERIMENTAL,
    structured_output_support=False,
    thinking_mode="not_applicable",
    contract_version="qwen-ocr-advanced-v1",
    min_pixels=3_072,
    max_pixels=8_388_608,
    max_image_bytes=7 * 1024 * 1024,
    supported_mime_types=frozenset(
        {"image/png", "image/jpeg", "image/webp"}
    ),
    confidence_available=False,
    max_output_tokens=4_096,
)
_QIANWEN_EMBEDDING = ProviderCatalogEntry(
    provider="qianwen",
    model_id=QIANWEN_EMBEDDING_MODEL_ID,
    capabilities=frozenset({Capability.EMBEDDING}),
    protocol=ProviderProtocol.OPENAI_EMBEDDINGS,
    available_regions=frozenset(QianwenRegion),
    adapter_status=AdapterStatus.EXPERIMENTAL,
    structured_output_support=False,
    thinking_mode="not_applicable",
    contract_version=QIANWEN_EMBEDDING_CONTRACT_VERSION,
    embedding_dimension=QIANWEN_EMBEDDING_DIMENSION,
    max_batch_size=10,
    max_batch_tokens_by_region={
        QianwenRegion.CN_BEIJING: 33_000,
        QianwenRegion.AP_SOUTHEAST_1: 8_192,
    },
    upstream_snapshot_immutable=False,
)
_QIANWEN_IMAGE = ProviderCatalogEntry(
    provider="qianwen",
    model_id=QIANWEN_IMAGE_MODEL_ID,
    capabilities=frozenset({Capability.IMAGE}),
    protocol=ProviderProtocol.DASHSCOPE_MULTIMODAL_GENERATION,
    available_regions=frozenset(QianwenRegion),
    adapter_status=AdapterStatus.EXPERIMENTAL,
    structured_output_support=False,
    thinking_mode="not_applicable",
    contract_version=QIANWEN_IMAGE_CONTRACT_VERSION,
    min_pixels=512 * 512,
    max_pixels=2048 * 2048,
    max_image_bytes=10 * 1024 * 1024,
    supported_mime_types=frozenset(
        {"image/png", "image/jpeg", "image/webp"}
    ),
    upstream_snapshot_immutable=True,
    max_reference_images=3,
    max_output_images=1,
)
_CATALOG: dict[tuple[str, str], ProviderCatalogEntry] = {
    ("qianwen", QIANWEN_TEXT_MODEL_ID): _QIANWEN_TEXT,
    ("qianwen", QIANWEN_OCR_MODEL_ID): _QIANWEN_OCR,
    ("qianwen", QIANWEN_EMBEDDING_MODEL_ID): _QIANWEN_EMBEDDING,
    ("qianwen", QIANWEN_IMAGE_MODEL_ID): _QIANWEN_IMAGE,
}


def get_catalog_entry(provider: str, model_id: str) -> ProviderCatalogEntry:
    try:
        return _CATALOG[(provider, model_id)]
    except KeyError as error:
        raise LookupError("model is not present in the Provider Catalog") from error


def list_catalog_entries(
    provider: str = "qianwen",
) -> tuple[ProviderCatalogEntry, ...]:
    return tuple(
        sorted(
            (
                entry
                for (entry_provider, _), entry in _CATALOG.items()
                if entry_provider == provider
            ),
            key=lambda entry: entry.model_id,
        )
    )


def validate_provider_workspace_id(provider_workspace_id: str) -> str:
    if (
        _PROVIDER_WORKSPACE_ID.fullmatch(provider_workspace_id) is None
        or provider_workspace_id == "llm-localhost"
    ):
        raise ValueError("invalid Provider Workspace ID")
    return provider_workspace_id


def build_qianwen_endpoint(
    region: QianwenRegion,
    provider_workspace_id: str,
) -> str:
    try:
        safe_region = QianwenRegion(region)
    except ValueError as error:
        raise ValueError("unsupported Qianwen region") from error
    safe_workspace_id = validate_provider_workspace_id(provider_workspace_id)
    return (
        f"https://{safe_workspace_id}.{safe_region.value}.maas.aliyuncs.com/"
        "compatible-mode/v1/chat/completions"
    )


def build_qianwen_ocr_endpoint(
    region: QianwenRegion,
    provider_workspace_id: str,
) -> str:
    try:
        safe_region = QianwenRegion(region)
    except ValueError as error:
        raise ValueError("unsupported Qianwen region") from error
    safe_workspace_id = validate_provider_workspace_id(provider_workspace_id)
    return (
        f"https://{safe_workspace_id}.{safe_region.value}.maas.aliyuncs.com/"
        "api/v1/services/aigc/multimodal-generation/generation"
    )


def build_qianwen_embedding_endpoint(
    region: QianwenRegion,
    provider_workspace_id: str,
) -> str:
    try:
        safe_region = QianwenRegion(region)
    except ValueError as error:
        raise ValueError("unsupported Qianwen region") from error
    safe_workspace_id = validate_provider_workspace_id(provider_workspace_id)
    return (
        f"https://{safe_workspace_id}.{safe_region.value}.maas.aliyuncs.com/"
        "compatible-mode/v1/embeddings"
    )


def build_qianwen_image_endpoint(
    region: QianwenRegion,
    provider_workspace_id: str,
) -> str:
    try:
        safe_region = QianwenRegion(region)
    except ValueError as error:
        raise ValueError("unsupported Qianwen region") from error
    safe_workspace_id = validate_provider_workspace_id(provider_workspace_id)
    return (
        f"https://{safe_workspace_id}.{safe_region.value}.maas.aliyuncs.com/"
        "api/v1/services/aigc/multimodal-generation/generation"
    )
