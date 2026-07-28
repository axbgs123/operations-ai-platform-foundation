from pydantic import ValidationError
import pytest

from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import (
    QIANWEN_TEXT_MODEL_ID,
    ProviderProtocol,
    QianwenRegion,
    build_qianwen_endpoint,
    get_catalog_entry,
)


def test_qianwen_text_catalog_is_exact_and_experimental() -> None:
    entry = get_catalog_entry("qianwen", QIANWEN_TEXT_MODEL_ID)

    assert entry.provider == "qianwen"
    assert entry.model_id == "qwen3.5-plus-2026-04-20"
    assert entry.capabilities == frozenset({Capability.TEXT})
    assert entry.protocol is ProviderProtocol.OPENAI_CHAT_COMPLETIONS
    assert entry.available_regions == frozenset(QianwenRegion)
    assert entry.adapter_status is AdapterStatus.EXPERIMENTAL
    assert entry.structured_output_support is True
    assert entry.thinking_mode == "disabled_for_structured_output"
    assert entry.contract_version == "qianwen-chat-json-v1"


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        (
            QianwenRegion.CN_BEIJING,
            "https://llm-abcd1234.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1/chat/completions",
        ),
        (
            QianwenRegion.AP_SOUTHEAST_1,
            "https://llm-abcd1234.ap-southeast-1.maas.aliyuncs.com/"
            "compatible-mode/v1/chat/completions",
        ),
    ],
)
def test_endpoint_is_constructed_from_region_and_workspace_id(
    region: QianwenRegion,
    expected: str,
) -> None:
    assert build_qianwen_endpoint(region, "llm-abcd1234") == expected


@pytest.mark.parametrize(
    "workspace_id",
    [
        "llm-abc",
        "llm-ABCD",
        "llm-a.bcd",
        "llm-a/bcd",
        "llm-localhost",
        "localhost",
        "127.0.0.1",
        "llm-user:pass@example",
        "llm-abcd#fragment",
        "https://llm-abcd.cn-beijing.maas.aliyuncs.com",
        "llm-" + ("a" * 65),
    ],
)
def test_endpoint_rejects_untrusted_workspace_identifiers(
    workspace_id: str,
) -> None:
    with pytest.raises(ValueError, match="Provider Workspace ID"):
        build_qianwen_endpoint(QianwenRegion.CN_BEIJING, workspace_id)


def test_unknown_region_and_model_are_rejected() -> None:
    with pytest.raises(ValueError, match="region"):
        build_qianwen_endpoint("us-west-1", "llm-abcd1234")  # type: ignore[arg-type]
    with pytest.raises(LookupError, match="Catalog"):
        get_catalog_entry("qianwen", "qwen-latest")
    with pytest.raises(LookupError, match="Catalog"):
        get_catalog_entry("unknown", QIANWEN_TEXT_MODEL_ID)


def test_catalog_entry_is_frozen_and_forbids_client_capability_expansion() -> None:
    entry = get_catalog_entry("qianwen", QIANWEN_TEXT_MODEL_ID)

    with pytest.raises(ValidationError):
        entry.capabilities = frozenset({Capability.TEXT, Capability.VISION})
