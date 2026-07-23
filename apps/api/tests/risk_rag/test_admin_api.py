from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.content.test_content_detail import (
    configured_client,
    create_admin_and_account,
)


NOW = "2026-07-23T12:00:00Z"


def _member_code(client: TestClient, workspace_id: str, csrf: str, role: str) -> str:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/members/codes",
        headers={"X-CSRF-Token": csrf},
        json={"role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()["code"]


def _login(app, code: str, name: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    response = client.post(
        "/v1/sessions/invite",
        json={"code": code, "display_name": name},
    )
    assert response.status_code == 201, response.text
    return client, response.json()["csrf_token"]


def _create_document(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    platform: str = "douyin",
) -> dict:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/risk-documents",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": platform,
            "source_level": "S3",
            "title": "人工合成 Task 7 知识",
            "private_document_id": f"synthetic-{uuid4()}",
            "authorization_status": "authorized",
            "effective_at": NOW,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _parse(client: TestClient, workspace_id: str, csrf: str, document_id: str) -> dict:
    response = client.post(
        f"/v1/workspaces/{workspace_id}/risk-documents/{document_id}/parse",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "parse-1"},
        json={
            "text": "SYNTHETIC_TASK7_DOUYIN_RULE",
            "source_location": "人工合成段落",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _activate_lifecycle(
    client: TestClient,
    workspace_id: str,
    csrf: str,
    document_id: str,
) -> dict:
    current = _parse(client, workspace_id, csrf, document_id)
    assert current["status"] == "parsed"
    for action in ("submit-review", "activate"):
        response = client.post(
            f"/v1/workspaces/{workspace_id}/risk-documents/{document_id}/{action}",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": f"{action}-1",
            },
        )
        assert response.status_code == 200, response.text
        current = response.json()
    assert current["status"] == "active"
    return current


def test_admin_editor_viewer_knowledge_permissions_and_cross_workspace_404() -> None:
    with configured_client() as admin_client:
        workspace_id, admin_csrf, _ = create_admin_and_account(admin_client)
        editor_client, editor_csrf = _login(
            admin_client.app,
            _member_code(admin_client, workspace_id, admin_csrf, "editor"),
            "synthetic-editor",
        )
        viewer_client, viewer_csrf = _login(
            admin_client.app,
            _member_code(admin_client, workspace_id, admin_csrf, "viewer"),
            "synthetic-viewer",
        )
        try:
            document = _create_document(
                admin_client,
                workspace_id=workspace_id,
                csrf=admin_csrf,
            )
            for client, csrf in (
                (editor_client, editor_csrf),
                (viewer_client, viewer_csrf),
            ):
                listed = client.get(
                    f"/v1/workspaces/{workspace_id}/risk-documents",
                    params={"platform": "douyin"},
                )
                assert listed.status_code == 200
                assert listed.json()[0]["id"] == document["id"]
                forbidden = client.post(
                    f"/v1/workspaces/{workspace_id}/risk-documents/{document['id']}/parse",
                    headers={"X-CSRF-Token": csrf},
                    json={"text": "SYNTHETIC", "source_location": "人工段落"},
                )
                assert forbidden.status_code == 403

            parsed = _parse(
                admin_client,
                workspace_id,
                admin_csrf,
                document["id"],
            )
            assert parsed["status"] == "parsed"
            pending = admin_client.post(
                f"/v1/workspaces/{workspace_id}/risk-documents/{document['id']}/submit-review",
                headers={"X-CSRF-Token": admin_csrf},
            )
            assert pending.status_code == 200
            active = admin_client.post(
                f"/v1/workspaces/{workspace_id}/risk-documents/{document['id']}/activate",
                headers={"X-CSRF-Token": admin_csrf},
            )
            assert active.status_code == 200

            other_workspace = admin_client.post(
                "/v1/workspaces",
                json={"name": "synthetic-other-workspace"},
            ).json()
            hidden = admin_client.get(
                f"/v1/workspaces/{other_workspace['workspace_id']}/risk-documents/{document['id']}",
            )
            assert hidden.status_code == 404
            assert "SYNTHETIC_TASK7" not in hidden.text
        finally:
            editor_client.close()
            viewer_client.close()


def test_editor_cannot_review_activate_supersede_or_expire_and_viewer_cannot_scan(
) -> None:
    with configured_client() as admin_client:
        workspace_id, admin_csrf, account = create_admin_and_account(admin_client)
        editor_client, editor_csrf = _login(
            admin_client.app,
            _member_code(admin_client, workspace_id, admin_csrf, "editor"),
            "synthetic-editor",
        )
        viewer_client, viewer_csrf = _login(
            admin_client.app,
            _member_code(admin_client, workspace_id, admin_csrf, "viewer"),
            "synthetic-viewer",
        )
        try:
            document = _create_document(
                admin_client,
                workspace_id=workspace_id,
                csrf=admin_csrf,
            )
            parse = editor_client.post(
                f"/v1/workspaces/{workspace_id}/risk-documents/{document['id']}/parse",
                headers={"X-CSRF-Token": editor_csrf},
                json={"text": "SYNTHETIC", "source_location": "人工段落"},
            )
            assert parse.status_code == 403
            for action in ("submit-review", "activate", "supersede", "expire"):
                response = editor_client.post(
                    f"/v1/workspaces/{workspace_id}/risk-documents/{document['id']}/{action}",
                    headers={"X-CSRF-Token": editor_csrf},
                )
                assert response.status_code == 403
            scan = viewer_client.post(
                f"/v1/workspaces/{workspace_id}/risk-scans",
                headers={"X-CSRF-Token": viewer_csrf},
                json={
                    "workspace_id": workspace_id,
                    "account_id": account["id"],
                    "content_id": str(uuid4()),
                    "platform": "douyin",
                    "node": "after_ingestion",
                    "title": "SYNTHETIC",
                    "body": "SYNTHETIC",
                    "ocr": {"status": "empty", "regions": []},
                    "idempotency_key": "viewer-scan",
                    "versions": {
                        "rule_version": "rules-v1",
                        "evidence_version": "evidence-v1",
                        "embedding_model_id": "mock-risk-embedding",
                        "embedding_version": "embed-v1",
                        "embedding_dimension": 3,
                        "rag_model_version": "mock-rag-v1",
                        "scanner_version": "scanner-v1",
                    },
                    "requested_at": NOW,
                },
            )
            assert scan.status_code == 403
        finally:
            editor_client.close()
            viewer_client.close()


def test_platform_isolation_current_versions_and_version_chain() -> None:
    with configured_client() as client:
        workspace_id, csrf, _ = create_admin_and_account(client)
        douyin = _create_document(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            platform="douyin",
        )
        xhs = _create_document(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            platform="xiaohongshu",
        )
        _activate_lifecycle(client, workspace_id, csrf, douyin["id"])
        _activate_lifecycle(client, workspace_id, csrf, xhs["id"])

        douyin_current = client.get(
            f"/v1/workspaces/{workspace_id}/risk-documents/current",
            params={"platform": "douyin", "at": NOW},
        )
        xhs_current = client.get(
            f"/v1/workspaces/{workspace_id}/risk-documents/current",
            params={"platform": "xiaohongshu", "at": NOW},
        )
        assert {item["platform"] for item in douyin_current.json()} == {"douyin"}
        assert {item["platform"] for item in xhs_current.json()} == {"xiaohongshu"}

        versions = client.get(
            f"/v1/workspaces/{workspace_id}/risk-documents/{douyin['id']}/versions"
        )
        assert versions.status_code == 200
        assert versions.json()[0]["id"] == douyin["id"]


def test_feedback_and_evaluation_management_routes() -> None:
    with configured_client() as client:
        workspace_id, csrf, account = create_admin_and_account(client)
        feedback_code = _member_code(client, workspace_id, csrf, "editor")
        editor, editor_csrf = _login(client.app, feedback_code, "feedback-editor")
        try:
            content = client.post(
                "/v1/contents",
                headers={"X-CSRF-Token": csrf},
                json={
                    "workspace_id": workspace_id,
                    "account_id": account["id"],
                    "platform": "douyin",
                    "title": "SYNTHETIC",
                    "body": "SYNTHETIC",
                },
            ).json()
            scan = client.post(
                f"/v1/workspaces/{workspace_id}/risk-scans",
                headers={"X-CSRF-Token": csrf},
                json={
                    "workspace_id": workspace_id,
                    "account_id": account["id"],
                    "content_id": content["id"],
                    "platform": "douyin",
                    "node": "after_ingestion",
                    "title": "SYNTHETIC",
                    "body": "SYNTHETIC",
                    "ocr": {"status": "empty", "regions": []},
                    "idempotency_key": "admin-scan-feedback",
                    "versions": {
                        "rule_version": "rules-v1",
                        "evidence_version": "evidence-v1",
                        "embedding_model_id": "mock-risk-embedding",
                        "embedding_version": "embed-v1",
                        "embedding_dimension": 3,
                        "rag_model_version": "mock-rag-v1",
                        "scanner_version": "scanner-v1",
                    },
                    "requested_at": NOW,
                },
            ).json()
            feedback = editor.post(
                f"/v1/workspaces/{workspace_id}/risk-scans/{scan['id']}/feedback",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "finding_reference": "synthetic-finding",
                    "feedback_type": "false_positive",
                    "idempotency_key": "feedback-api-1",
                    "comment": "人工合成反馈",
                },
            )
            assert feedback.status_code == 201, feedback.text
            pending = feedback.json()
            candidates = client.get(
                f"/v1/workspaces/{workspace_id}/risk-feedback/candidates",
                params={"platform": "douyin"},
            )
            assert candidates.status_code == 200
            assert candidates.json() == []
            reviewed = client.post(
                f"/v1/workspaces/{workspace_id}/risk-feedback/{pending['id']}/review",
                headers={"X-CSRF-Token": csrf},
                json={"status": "approved", "note": "人工审核"},
            )
            assert reviewed.status_code == 200
            assert client.get(
                f"/v1/workspaces/{workspace_id}/risk-feedback/candidates",
                params={"platform": "douyin"},
            ).json()[0]["can_modify_public_rules"] is False
            evaluation = client.get(
                f"/v1/workspaces/{workspace_id}/risk-evaluations",
                params={"platform": "douyin"},
            )
            assert evaluation.status_code == 200
            assert evaluation.json()["quality_label"] == "ENGINEERING_REGRESSION_ONLY"
            assert evaluation.json()["production_quality_claim_allowed"] is False
        finally:
            editor.close()
