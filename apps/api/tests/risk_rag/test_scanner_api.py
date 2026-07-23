from fastapi.testclient import TestClient

from tests.content.test_content_detail import (
    configured_client,
    create_admin_and_account,
)


def _create_content(
    client: TestClient,
    *,
    workspace_id: str,
    account_id: str,
    csrf: str,
) -> dict:
    response = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account_id,
            "platform": "douyin",
            "title": "人工合成扫描标题",
            "body": "人工合成扫描正文",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _scan_payload(
    *,
    workspace_id: str,
    account_id: str,
    content_id: str,
    idempotency_key: str,
    node: str = "after_ingestion",
) -> dict:
    return {
        "workspace_id": workspace_id,
        "account_id": account_id,
        "content_id": content_id,
        "cover_asset_id": None,
        "platform": "douyin",
        "node": node,
        "title": "人工合成扫描标题",
        "body": "人工合成扫描正文",
        "ocr": {"status": "empty", "regions": []},
        "idempotency_key": idempotency_key,
        "versions": {
            "rule_version": "rules-v1",
            "evidence_version": "evidence-v1",
            "embedding_model_id": "mock-risk-embedding",
            "embedding_version": "embed-v1",
            "embedding_dimension": 3,
            "rag_model_version": "mock-rag-v1",
            "scanner_version": "scanner-v1",
        },
        "requested_at": "2026-07-23T08:00:00Z",
    }


def _new_session(
    app,
    *,
    code: str,
    display_name: str,
) -> tuple[TestClient, str]:
    client = TestClient(app)
    login = client.post(
        "/v1/sessions/invite",
        json={"code": code, "display_name": display_name},
    )
    assert login.status_code == 201, login.text
    return client, login.json()["csrf_token"]


def test_admin_and_editor_trigger_viewer_reads_and_cross_workspace_is_404() -> None:
    with configured_client() as admin_client:
        workspace_id, admin_csrf, account = create_admin_and_account(
            admin_client
        )
        content = _create_content(
            admin_client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=admin_csrf,
        )
        created = admin_client.post(
            f"/v1/workspaces/{workspace_id}/risk-scans",
            headers={"X-CSRF-Token": admin_csrf},
            json=_scan_payload(
                workspace_id=workspace_id,
                account_id=account["id"],
                content_id=content["id"],
                idempotency_key="api-scan-admin",
            ),
        )
        assert created.status_code == 201, created.text
        scan = created.json()
        assert scan["status"] == "succeeded"
        assert scan["result"]["error_code"] == "NO_ACTIVE_RISK_EVIDENCE"
        assert scan["result"]["findings"] == []
        assert scan["result"]["disclaimer"] == "辅助判断，不保证通过平台审核"

        editor_code = admin_client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": admin_csrf},
            json={"role": "editor"},
        ).json()["code"]
        viewer_code = admin_client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": admin_csrf},
            json={"role": "viewer"},
        ).json()["code"]
        editor_client, editor_csrf = _new_session(
            admin_client.app,
            code=editor_code,
            display_name="scan-editor",
        )
        viewer_client, viewer_csrf = _new_session(
            admin_client.app,
            code=viewer_code,
            display_name="scan-viewer",
        )
        try:
            editor_created = editor_client.post(
                f"/v1/workspaces/{workspace_id}/risk-scans",
                headers={"X-CSRF-Token": editor_csrf},
                json=_scan_payload(
                    workspace_id=workspace_id,
                    account_id=account["id"],
                    content_id=content["id"],
                    idempotency_key="api-scan-editor",
                    node="before_publication",
                ),
            )
            assert editor_created.status_code == 201, editor_created.text

            forbidden = viewer_client.post(
                f"/v1/workspaces/{workspace_id}/risk-scans",
                headers={"X-CSRF-Token": viewer_csrf},
                json=_scan_payload(
                    workspace_id=workspace_id,
                    account_id=account["id"],
                    content_id=content["id"],
                    idempotency_key="api-scan-viewer",
                ),
            )
            assert forbidden.status_code == 403
            readable = viewer_client.get(
                f"/v1/workspaces/{workspace_id}/risk-scans/{scan['id']}"
            )
            assert readable.status_code == 200
        finally:
            editor_client.close()
            viewer_client.close()

        other_workspace = admin_client.post(
            "/v1/workspaces",
            json={"name": "other-risk-scan-workspace"},
        ).json()
        other_login = admin_client.post(
            "/v1/sessions/invite",
            json={
                "code": other_workspace["admin_code"],
                "display_name": "other-admin",
            },
        )
        assert other_login.status_code == 201
        hidden = admin_client.get(
            (
                f"/v1/workspaces/{other_workspace['workspace_id']}"
                f"/risk-scans/{scan['id']}"
            )
        )
        assert hidden.status_code == 404


def test_scan_history_endpoint_returns_newest_first_without_overwrite() -> None:
    with configured_client() as client:
        workspace_id, csrf, account = create_admin_and_account(client)
        content = _create_content(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )
        first = client.post(
            f"/v1/workspaces/{workspace_id}/risk-scans",
            headers={"X-CSRF-Token": csrf},
            json=_scan_payload(
                workspace_id=workspace_id,
                account_id=account["id"],
                content_id=content["id"],
                idempotency_key="api-history-1",
            ),
        ).json()
        second = client.post(
            f"/v1/workspaces/{workspace_id}/risk-scans",
            headers={"X-CSRF-Token": csrf},
            json=_scan_payload(
                workspace_id=workspace_id,
                account_id=account["id"],
                content_id=content["id"],
                idempotency_key="api-history-2",
                node="after_generation",
            ),
        ).json()

        history = client.get(
            f"/v1/workspaces/{workspace_id}/risk-scans",
            params={"content_id": content["id"]},
        )

        assert history.status_code == 200
        assert [item["id"] for item in history.json()] == [
            second["id"],
            first["id"],
        ]
        assert second["previous_scan_id"] == first["id"]
