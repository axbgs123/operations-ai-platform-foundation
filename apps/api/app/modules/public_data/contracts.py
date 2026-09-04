from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.modules.content.account_models import Platform


@dataclass(frozen=True, slots=True)
class ResolvedPublicContent:
    platform: Platform
    platform_content_id: str
    public_url: str
    locator: dict[str, str]


@dataclass(frozen=True, slots=True)
class PublicMetricObservation:
    endpoint_contract: str
    provider_request_id: str | None
    fetched_at: datetime
    raw_response: dict[str, object]
    metrics: dict[str, int | float | None]


class PublicDataProvider(Protocol):
    name: str

    def test_connection(self) -> str | None: ...

    def resolve_content(
        self,
        *,
        platform: Platform,
        public_url: str,
        platform_content_id: str | None = None,
    ) -> ResolvedPublicContent: ...

    def fetch_content_metrics(
        self,
        *,
        platform: Platform,
        locator: dict[str, str],
    ) -> PublicMetricObservation: ...


class PublicProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
