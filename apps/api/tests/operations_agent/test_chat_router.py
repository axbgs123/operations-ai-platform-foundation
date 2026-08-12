from tests.imports.helpers import configured_client, create_workspace_account


def test_chat_api_persists_history_and_enforces_csrf() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, _ = create_workspace_account(client)
        missing_csrf = client.post(
            f"/v1/workspaces/{workspace_id}/agent/chats",
            headers={"Idempotency-Key": "chat-api-missing-csrf"},
        )
        assert missing_csrf.status_code == 403

        created = client.post(
            f"/v1/workspaces/{workspace_id}/agent/chats",
            headers={
                "Idempotency-Key": "chat-api-1",
                "X-CSRF-Token": csrf,
            },
        )
        assert created.status_code == 201, created.text
        chat_id = created.json()["id"]
        message = client.post(
            f"/v1/workspaces/{workspace_id}/agent/chats/{chat_id}/messages",
            headers={
                "Idempotency-Key": "chat-message-api-1",
                "X-CSRF-Token": csrf,
            },
            json={"content": "帮我看一下账号表现"},
        )
        assert message.status_code == 201, message.text
        assert message.json()["sequence_no"] == 1

        turn = client.post(
            f"/v1/workspaces/{workspace_id}/agent/chats/{chat_id}/turns",
            headers={
                "Idempotency-Key": "chat-turn-api-1",
                "X-CSRF-Token": csrf,
            },
            json={"content": "你好"},
        )
        assert turn.status_code == 200, turn.text
        assert [item["role"] for item in turn.json()["messages"]] == [
            "user",
            "user",
            "assistant",
        ]
        assert "你好" in turn.json()["messages"][-1]["content"]

        detail = client.get(
            f"/v1/workspaces/{workspace_id}/agent/chats/{chat_id}"
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["title"] == "帮我看一下账号表现"
        assert [item["content"] for item in detail.json()["messages"]][:2] == [
            "帮我看一下账号表现",
            "你好",
        ]
        listing = client.get(
            f"/v1/workspaces/{workspace_id}/agent/chats?page=1&page_size=10"
        )
        assert listing.status_code == 200, listing.text
        assert [item["id"] for item in listing.json()["items"]] == [chat_id]

        archived = client.post(
            f"/v1/workspaces/{workspace_id}/agent/chats/{chat_id}/archive",
            headers={"X-CSRF-Token": csrf},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"
