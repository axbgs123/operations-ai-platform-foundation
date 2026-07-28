from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.models.capabilities import AdapterStatus, Capability


QIANWEN_TEXT_MODEL_ID: Literal["qwen3.5-plus-2026-04-20"] = (
    "qwen3.5-plus-2026-04-20"
)
_PROVIDER_WORKSPACE_ID = re.compile(r"^llm-[a-z0-9]{4,64}$")


class QianwenRegion(StrEnum):
    CN_BEIJING = "cn-beijing"
    AP_SOUTHEAST_1 = "ap-southeast-1"


class ProviderProtocol(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"


class ProviderCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["qianwen"]
    model_id: Literal["qwen3.5-plus-2026-04-20"]
    capabilities: frozenset[Capability]
    protocol: Literal[ProviderProtocol.OPENAI_CHAT_COMPLETIONS]
    available_regions: frozenset[QianwenRegion]
    adapter_status: Literal[AdapterStatus.EXPERIMENTAL]
    structured_output_support: Literal[True]
    thinking_mode: Literal["disabled_for_structured_output"]
    contract_version: Literal["qianwen-chat-json-v1"]


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
_CATALOG: dict[tuple[str, str], ProviderCatalogEntry] = {
    ("qianwen", QIANWEN_TEXT_MODEL_ID): _QIANWEN_TEXT
}


def get_catalog_entry(provider: str, model_id: str) -> ProviderCatalogEntry:
    try:
        return _CATALOG[(provider, model_id)]
    except KeyError as error:
        raise LookupError("model is not present in the Provider Catalog") from error


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
