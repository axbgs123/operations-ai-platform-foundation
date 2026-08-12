from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import ip_address
import socket
from typing import Any
from urllib.parse import unquote, urlsplit


class UnsafeProviderEndpoint(ValueError):
    """Raised when a configured provider could reach an unsafe target."""


Resolver = Callable[..., Sequence[tuple[Any, ...]]]


def _normalized_ip(value: str, *, allow_loopback: bool) -> str:
    try:
        parsed = ip_address(value)
    except ValueError as error:
        raise UnsafeProviderEndpoint("provider host did not resolve safely") from error
    if parsed.is_loopback and allow_loopback:
        return parsed.compressed
    if not parsed.is_global:
        raise UnsafeProviderEndpoint("provider endpoint must use public addresses")
    return parsed.compressed


@dataclass(frozen=True)
class NormalizedProviderEndpoint:
    base_url: str
    resolved_ips: tuple[str, ...]
    allow_loopback: bool

    @property
    def models_url(self) -> str:
        return f"{self.base_url}/models"

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def require_peer(self, peer_ip: str) -> None:
        try:
            normalized = _normalized_ip(
                peer_ip,
                allow_loopback=self.allow_loopback,
            )
        except UnsafeProviderEndpoint as error:
            raise UnsafeProviderEndpoint(
                "provider connection was blocked after DNS rebind"
            ) from error
        if normalized not in self.resolved_ips:
            raise UnsafeProviderEndpoint(
                "provider connection was blocked after DNS rebind"
            )


def normalize_openai_base_url(
    value: str,
    *,
    app_env: str,
    resolver: Resolver = socket.getaddrinfo,
) -> NormalizedProviderEndpoint:
    raw = value.strip()
    if not raw or "\\" in raw or any(ord(character) < 32 for character in raw):
        raise UnsafeProviderEndpoint("invalid provider endpoint")
    try:
        parsed = urlsplit(raw)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError) as error:
        raise UnsafeProviderEndpoint("invalid provider endpoint") from error
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise UnsafeProviderEndpoint("provider endpoint must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeProviderEndpoint("provider endpoint cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise UnsafeProviderEndpoint("provider endpoint cannot contain query or fragment")
    decoded_path = unquote(parsed.path)
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        raise UnsafeProviderEndpoint("provider endpoint path is unsafe")

    host = parsed.hostname.rstrip(".").lower()
    explicit_loopback = host == "localhost" or host.endswith(".localhost")
    try:
        literal = ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and literal.is_loopback:
        explicit_loopback = True
    allow_loopback = app_env == "development" and explicit_loopback
    if parsed.scheme != "https" and not allow_loopback:
        raise UnsafeProviderEndpoint("provider endpoint must use HTTPS")

    resolved: tuple[str, ...]
    if explicit_loopback:
        if not allow_loopback:
            raise UnsafeProviderEndpoint("loopback provider endpoint is development-only")
        if literal is not None:
            resolved = (_normalized_ip(literal.compressed, allow_loopback=True),)
        else:
            resolved = ("127.0.0.1", "::1")
    elif literal is not None:
        resolved = (_normalized_ip(literal.compressed, allow_loopback=False),)
    else:
        try:
            answers = resolver(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise UnsafeProviderEndpoint("provider host could not resolve") from error
        if not answers:
            raise UnsafeProviderEndpoint("provider host could not resolve")
        resolved = tuple(
            dict.fromkeys(
                _normalized_ip(str(answer[4][0]), allow_loopback=False)
                for answer in answers
            )
        )

    display_host = f"[{host}]" if literal is not None and literal.version == 6 else host
    default_port = 443 if parsed.scheme == "https" else 80
    authority = display_host if port == default_port else f"{display_host}:{port}"
    path = parsed.path.rstrip("/")
    return NormalizedProviderEndpoint(
        base_url=f"{parsed.scheme}://{authority}{path}",
        resolved_ips=resolved,
        allow_loopback=allow_loopback,
    )
