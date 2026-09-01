from app.modules.imports.extension_devices import InMemoryChallengeClient


def test_lite_challenge_store_is_single_use() -> None:
    client = InMemoryChallengeClient()

    assert client.set("challenge", "payload", ex=60, nx=True) is True
    assert client.set("challenge", "replacement", ex=60, nx=True) is False
    assert client.eval("ignored", 1, "challenge") == "payload"
    assert client.eval("ignored", 1, "challenge") is False
