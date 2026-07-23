from collections.abc import Callable, Sequence
from dataclasses import dataclass
from ipaddress import ip_address
import socket
from typing import Any
from urllib.parse import urlsplit


class UnsafeSourceUrl(ValueError):
    """Raised when a source URL could reach a non-public network target."""


Resolver = Callable[..., Sequence[tuple[Any, ...]]]


def _public_ip(value: str) -> str:
    try:
        parsed = ip_address(value)
    except ValueError as error:
        raise UnsafeSourceUrl("source URL did not resolve to an IP address") from error
    if not parsed.is_global:
        raise UnsafeSourceUrl("source URL must resolve only to public IP addresses")
    return parsed.compressed


@dataclass(frozen=True)
class ValidatedSourceUrl:
    url: str
    resolved_ips: tuple[str, ...]

    def require_peer(self, peer_ip: str) -> None:
        try:
            normalized = _public_ip(peer_ip)
        except UnsafeSourceUrl as error:
            raise UnsafeSourceUrl(
                "source connection was blocked after DNS rebind"
            ) from error
        if normalized not in self.resolved_ips:
            raise UnsafeSourceUrl("source connection was blocked after DNS rebind")


def validate_source_url(
    url: str,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedSourceUrl:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise UnsafeSourceUrl("invalid source URL") from error
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeSourceUrl("source URL must use HTTP or HTTPS")
    if parsed.hostname is None:
        raise UnsafeSourceUrl("source URL must include a host")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise UnsafeSourceUrl("source URL cannot include credentials or a fragment")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeSourceUrl("source URL must resolve only to public IP addresses")

    try:
        literal = ip_address(host)
    except ValueError:
        try:
            answers = resolver(host, port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise UnsafeSourceUrl("source URL host could not resolve") from error
        if not answers:
            raise UnsafeSourceUrl("source URL host could not resolve")
        resolved = tuple(
            dict.fromkeys(_public_ip(str(answer[4][0])) for answer in answers)
        )
    else:
        resolved = (_public_ip(literal.compressed),)

    return ValidatedSourceUrl(url=url, resolved_ips=resolved)
