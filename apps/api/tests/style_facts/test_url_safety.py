import socket

import pytest

from app.modules.style_facts.url_safety import UnsafeSourceUrl, validate_source_url


def resolver_for(*addresses: str):
    def resolve(host: str, port: int, *, type: int):
        assert type == socket.SOCK_STREAM
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, type, 6, "", (address, port))
            for address in addresses
        ]

    return resolve


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file.txt",
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "http://10.0.0.4/private",
        "http://172.16.0.4/private",
        "http://192.168.1.4/private",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/admin",
        "http://[fe80::1]/private",
    ],
)
def test_rejects_non_http_and_non_public_source_targets(url: str) -> None:
    with pytest.raises(UnsafeSourceUrl):
        validate_source_url(url)


def test_rejects_hostname_when_any_dns_answer_is_not_public() -> None:
    with pytest.raises(UnsafeSourceUrl, match="public"):
        validate_source_url(
            "https://facts.example/product",
            resolver=resolver_for("93.184.216.34", "10.0.0.7"),
        )


def test_pins_public_dns_answers_and_rejects_rebound_connection_peer() -> None:
    validated = validate_source_url(
        "https://facts.example/product",
        resolver=resolver_for("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )

    assert validated.url == "https://facts.example/product"
    assert validated.resolved_ips == (
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    )
    validated.require_peer("93.184.216.34")
    with pytest.raises(UnsafeSourceUrl, match="rebind"):
        validated.require_peer("169.254.169.254")


def test_rejects_credentials_fragments_and_unresolvable_hosts() -> None:
    for url in (
        "https://user:password@facts.example/product",
        "https://facts.example/product#internal",
    ):
        with pytest.raises(UnsafeSourceUrl):
            validate_source_url(url, resolver=resolver_for("93.184.216.34"))

    with pytest.raises(UnsafeSourceUrl, match="resolve"):
        validate_source_url(
            "https://missing.example/product",
            resolver=resolver_for(),
        )
