import json
import logging
import math
from uuid import uuid4

import httpx
from pydantic import SecretStr
import pytest

from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.adapters.qianwen_embedding import (
    MAX_EMBEDDING_BATCH_SIZE,
    MAX_EMBEDDING_TEXT_CHARS,
    QianwenRiskEmbedder,
)
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import (
    QIANWEN_EMBEDDING_CONTRACT_VERSION,
    QIANWEN_EMBEDDING_DIMENSION,
    QIANWEN_EMBEDDING_MODEL_ID,
    QianwenRegion,
    build_qianwen_embedding_endpoint,
    get_catalog_entry,
)


def _vector(seed: float = 1.0) -> list[float]:
    return [seed] + [0.001] * (QIANWEN_EMBEDDING_DIMENSION - 1)


def _response(
    data: list[dict[str, object]],
    *,
    status_code: int = 200,
    model_id: str = QIANWEN_EMBEDDING_MODEL_ID,
) -> httpx.Response:
    if status_code != 200:
        return httpx.Response(
            status_code,
            json={"message": "provider-sensitive-body-never-log"},
        )
    return httpx.Response(
        200,
        content=json.dumps(
            {
                "object": "list",
                "data": data,
                "model": model_id,
                "usage": {"prompt_tokens": 12, "total_tokens": 12},
            }
        ).encode(),
        headers={
            "content-type": "application/json",
            "x-request-id": "req-embedding-synthetic",
        },
    )


def _adapter(handler, *, sleeper=lambda _: None) -> QianwenRiskEmbedder:
    return QianwenRiskEmbedder(
        workspace_id=uuid4(),
        model_config_id=uuid4(),
        region=QianwenRegion.CN_BEIJING,
        provider_workspace_id="llm-abcd1234",
        api_key=SecretStr("sk-synthetic-never-real"),
        transport=httpx.MockTransport(handler),
        sleeper=sleeper,
    )


def test_catalog_pins_embedding_contract_and_dimension() -> None:
    entry = get_catalog_entry("qianwen", QIANWEN_EMBEDDING_MODEL_ID)

    assert entry.model_id == "text-embedding-v4"
    assert entry.capabilities == frozenset({Capability.EMBEDDING})
    assert entry.protocol == "openai_embeddings"
    assert entry.contract_version == "qianwen-text-embedding-v4-d1024-v1"
    assert entry.embedding_dimension == 1024
    assert entry.max_batch_size == 10
    assert entry.max_batch_tokens_by_region == {
        QianwenRegion.CN_BEIJING: 33_000,
        QianwenRegion.AP_SOUTHEAST_1: 8_192,
    }
    assert entry.adapter_status is AdapterStatus.EXPERIMENTAL
    assert entry.upstream_snapshot_immutable is False


@pytest.mark.parametrize(
    ("region", "host"),
    [
        (
            QianwenRegion.CN_BEIJING,
            "llm-abcd1234.cn-beijing.maas.aliyuncs.com",
        ),
        (
            QianwenRegion.AP_SOUTHEAST_1,
            "llm-abcd1234.ap-southeast-1.maas.aliyuncs.com",
        ),
    ],
)
def test_embedding_endpoint_is_server_constructed(
    region: QianwenRegion,
    host: str,
) -> None:
    assert build_qianwen_embedding_endpoint(region, "llm-abcd1234") == (
        f"https://{host}/compatible-mode/v1/embeddings"
    )


def test_batch_response_is_restored_to_input_order() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _response(
            [
                {"object": "embedding", "index": 1, "embedding": _vector(2.0)},
                {"object": "embedding", "index": 0, "embedding": _vector(1.0)},
            ]
        )

    result = _adapter(handler).embed_batch(["first", "second"])

    assert [row[0] for row in result] == [1.0, 2.0]
    payload = json.loads(captured[0].content)
    assert payload == {
        "model": QIANWEN_EMBEDDING_MODEL_ID,
        "input": ["first", "second"],
        "dimensions": QIANWEN_EMBEDDING_DIMENSION,
        "encoding_format": "float",
    }
    assert captured[0].url.path == "/compatible-mode/v1/embeddings"
    assert "base_url" not in payload


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "embedding": _vector()}],
        [
            {"index": 0, "embedding": _vector()},
            {"index": 0, "embedding": _vector(2.0)},
        ],
        [
            {"index": 0, "embedding": _vector()},
            {"index": 2, "embedding": _vector(2.0)},
        ],
        [{"index": 0, "embedding": _vector()[:-1]}, {"index": 1, "embedding": _vector()}],
        [
            {"index": 0, "embedding": [True] + _vector()[1:]},
            {"index": 1, "embedding": _vector()},
        ],
        [
            {"index": 0, "embedding": [1] + _vector()[1:]},
            {"index": 1, "embedding": _vector()},
        ],
        [
            {"index": 0, "embedding": [math.nan] + _vector()[1:]},
            {"index": 1, "embedding": _vector()},
        ],
        [
            {"index": 0, "embedding": [math.inf] + _vector()[1:]},
            {"index": 1, "embedding": _vector()},
        ],
        [
            {
                "index": 0,
                "embedding": [0.0] * QIANWEN_EMBEDDING_DIMENSION,
            },
            {"index": 1, "embedding": _vector()},
        ],
    ],
)
def test_invalid_embedding_response_is_rejected(
    data: list[dict[str, object]],
) -> None:
    with pytest.raises(ModelProviderError) as caught:
        _adapter(lambda _: _response(data)).embed_batch(["first", "second"])

    assert caught.value.code is ModelErrorCode.EMBEDDING_INVALID_RESPONSE


@pytest.mark.parametrize(
    "texts",
    [
        [],
        [""],
        ["  "],
        ["ok"] * (MAX_EMBEDDING_BATCH_SIZE + 1),
        ["x" * (MAX_EMBEDDING_TEXT_CHARS + 1)],
        ["🙂" * (MAX_EMBEDDING_TEXT_CHARS - 1)],
    ],
)
def test_input_limits_reject_before_network(texts: list[str]) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response([])

    with pytest.raises(ValueError):
        _adapter(handler).embed_batch(texts)

    assert calls == 0


def test_response_model_mismatch_is_rejected() -> None:
    with pytest.raises(ModelProviderError) as caught:
        _adapter(
            lambda _: _response(
                [{"object": "embedding", "index": 0, "embedding": _vector()}],
                model_id="different-model",
            )
        ).embed_batch(["safe"])

    assert caught.value.code is ModelErrorCode.EMBEDDING_INVALID_RESPONSE


@pytest.mark.parametrize(
    ("contract_version", "dimension"),
    [
        ("untrusted-contract", QIANWEN_EMBEDDING_DIMENSION),
        (
            QIANWEN_EMBEDDING_CONTRACT_VERSION,
            QIANWEN_EMBEDDING_DIMENSION - 1,
        ),
    ],
)
def test_adapter_rejects_contract_or_dimension_mismatch(
    contract_version: str,
    dimension: int,
) -> None:
    with pytest.raises(ValueError):
        QianwenRiskEmbedder(
            workspace_id=uuid4(),
            model_config_id=uuid4(),
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-abcd1234",
            api_key=SecretStr("sk-synthetic-never-real"),
            contract_version=contract_version,
            dimension=dimension,
            transport=httpx.MockTransport(lambda _: _response([])),
        )


@pytest.mark.parametrize(
    ("statuses", "expected_calls"),
    [
        ([401], 1),
        ([403], 1),
        ([400], 1),
        ([429, 200], 2),
        ([500, 200], 2),
    ],
)
def test_retry_policy_is_bounded(
    statuses: list[int],
    expected_calls: int,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        status = statuses[min(calls, len(statuses) - 1)]
        calls += 1
        if status == 200:
            return _response(
                [
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": _vector(),
                    }
                ]
            )
        return _response([], status_code=status)

    if statuses[-1] == 200:
        assert len(_adapter(handler).embed_batch(["safe"])) == 1
    else:
        with pytest.raises(ModelProviderError):
            _adapter(handler).embed_batch(["safe"])

    assert calls == expected_calls


def test_timeout_retries_once_and_logs_no_text_vector_or_key(caplog) -> None:
    calls = 0
    secret_text = "synthetic-private-risk-text"
    secret_key = "sk-synthetic-never-real"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("provider-body", request=request)
        return _response(
            [
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": _vector(),
                }
            ]
        )

    with caplog.at_level(
        logging.INFO,
        logger="operations_ai.models.qianwen_embedding",
    ):
        _adapter(handler).embed_batch([secret_text])

    assert calls == 2
    assert secret_text not in caplog.text
    assert secret_key not in caplog.text
    assert str(_vector()[:4]) not in caplog.text
    assert QIANWEN_EMBEDDING_MODEL_ID in caplog.text
    assert QIANWEN_EMBEDDING_CONTRACT_VERSION in caplog.text
