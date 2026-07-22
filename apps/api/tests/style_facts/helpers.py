from fastapi.testclient import TestClient

from tests.imports.helpers import create_workspace_account


def style_workspace(client: TestClient) -> tuple[str, str, dict]:
    return create_workspace_account(
        client,
        workspace_name="合成风格工作区",
        platform="douyin",
    )


def draft_content(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
    title: str,
    body: str = "这是只用于测试的草稿内容",
) -> dict:
    response = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": account["platform"],
            "content_type": "video",
            "title": title,
            "body": body,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def published_content(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
    title: str,
    body: str = "这是只用于测试的已发布内容。立即查看！✨",
) -> dict:
    created = draft_content(
        client,
        workspace_id=workspace_id,
        csrf=csrf,
        account=account,
        title=title,
        body=body,
    )
    response = client.patch(
        f"/v1/contents/{created['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"status": "published"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def select_sample(
    client: TestClient,
    *,
    workspace_id: str,
    account_id: str,
    content_id: str,
    csrf: str,
    column_campaign_id: str | None = None,
) -> dict:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/accounts/{account_id}/style-samples",
        headers={"X-CSRF-Token": csrf},
        json={
            "content_id": content_id,
            "column_campaign_id": column_campaign_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def extract_profile(
    client: TestClient,
    *,
    workspace_id: str,
    account_id: str,
    csrf: str,
    column_campaign_id: str | None = None,
) -> dict:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/accounts/{account_id}/style-profiles/extract",
        headers={"X-CSRF-Token": csrf},
        json={"column_campaign_id": column_campaign_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def confirm_profile(
    client: TestClient,
    *,
    workspace_id: str,
    profile_id: str,
    csrf: str,
) -> dict:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/style-profiles/{profile_id}/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    return response.json()
