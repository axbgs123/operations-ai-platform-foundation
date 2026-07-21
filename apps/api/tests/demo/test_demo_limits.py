from fastapi.testclient import TestClient

from app.main import app


def test_demo_mock_generation_has_session_and_ip_limits() -> None:
    with TestClient(app) as client:
        first_session = client.post("/v1/demo/sessions")
        assert first_session.status_code == 201
        assert "httponly" in first_session.headers["set-cookie"].lower()

        for expected_remaining in (2, 1, 0):
            generated = client.post(
                "/v1/demo/generations",
                json={"prompt": "为示例账号生成一个标题"},
            )
            assert generated.status_code == 200
            assert generated.json()["mock"] is True
            assert generated.json()["label"] == "Mock 输出"
            assert generated.json()["session_remaining"] == expected_remaining

        assert client.post(
            "/v1/demo/generations",
            json={"prompt": "超过单会话额度"},
        ).status_code == 429

        client.cookies.delete("demo_session")
        assert client.post("/v1/demo/sessions").status_code == 201
        for expected_ip_remaining in (1, 0):
            generated = client.post(
                "/v1/demo/generations",
                json={"prompt": "测试 IP 总额度"},
            )
            assert generated.status_code == 200
            assert generated.json()["ip_remaining"] == expected_ip_remaining

        ip_limited = client.post(
            "/v1/demo/generations",
            json={"prompt": "超过 IP 额度"},
        )
        assert ip_limited.status_code == 429
        assert ip_limited.json()["detail"] == "demo generation limit reached"
