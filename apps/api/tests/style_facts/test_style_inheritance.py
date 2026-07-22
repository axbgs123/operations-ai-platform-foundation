from uuid import uuid4

from app.modules.style_facts.style_models import AccountStyleProfile, StyleProfileStatus
from app.modules.style_facts.style_service import StyleInheritanceSwitches, StyleProfileService
from tests.imports.helpers import configured_client
from tests.style_facts.helpers import (
    confirm_profile,
    extract_profile,
    published_content,
    select_sample,
    style_workspace,
)


def _confirmed_account_profile(client, workspace_id, csrf, account) -> dict:
    content = published_content(
        client,
        workspace_id=workspace_id,
        csrf=csrf,
        account=account,
        title="账号默认风格：结论先行！",
    )
    select_sample(
        client,
        workspace_id=workspace_id,
        account_id=account["id"],
        content_id=content["id"],
        csrf=csrf,
    )
    draft = extract_profile(
        client,
        workspace_id=workspace_id,
        account_id=account["id"],
        csrf=csrf,
    )
    return confirm_profile(
        client,
        workspace_id=workspace_id,
        profile_id=draft["id"],
        csrf=csrf,
    )


def test_column_profile_temporarily_overrides_then_restores_account_profile() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        account_profile = _confirmed_account_profile(
            client, workspace_id, csrf, account
        )
        campaign = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/columns-campaigns",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "暑期栏目",
                "kind": "column",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-31T23:59:59Z",
            },
        )
        assert campaign.status_code == 201, campaign.text
        campaign_id = campaign.json()["id"]
        column_content = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="栏目专属风格：暑期效率指南？",
        )
        select_sample(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            content_id=column_content["id"],
            csrf=csrf,
            column_campaign_id=campaign_id,
        )
        column_draft = extract_profile(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
            column_campaign_id=campaign_id,
        )
        column_profile = confirm_profile(
            client,
            workspace_id=workspace_id,
            profile_id=column_draft["id"],
            csrf=csrf,
        )

        active = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-style",
            params={
                "column_campaign_id": campaign_id,
                "at": "2026-08-15T08:00:00Z",
            },
        )
        assert active.status_code == 200
        assert active.json()["source"] == "column_override"
        assert active.json()["profile_id"] == column_profile["id"]
        assert active.json()["style"] != {
            **account_profile["style"],
            "prohibited": account_profile["style"]["prohibited"],
        }

        expired = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-style",
            params={
                "column_campaign_id": campaign_id,
                "at": "2026-09-01T08:00:00Z",
            },
        )
        assert expired.status_code == 200
        assert expired.json()["source"] == "account_default"
        assert expired.json()["profile_id"] == account_profile["id"]

        repeated_account = extract_profile(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )
        assert [source["content_id"] for source in repeated_account["sample_sources"]] == [
            account_profile["sample_sources"][0]["content_id"]
        ]

        naive = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-style",
            params={
                "column_campaign_id": campaign_id,
                "at": "2026-08-15T08:00:00",
            },
        )
        assert naive.status_code == 422


def test_disabling_each_inheritance_switch_removes_that_history_from_context() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        _confirmed_account_profile(client, workspace_id, csrf, account)

        effective = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-style",
            params={
                "inherit_title": "false",
                "inherit_copy": "false",
                "inherit_cover": "false",
            },
        )

        assert effective.status_code == 200
        assert effective.json()["style"] == {}
        assert effective.json()["switches"] == {
            "title": False,
            "copy": False,
            "cover": False,
        }
        assert "prohibited" not in effective.json()["style"]


def test_disabled_sections_do_not_leak_matching_prohibitions() -> None:
    profile = AccountStyleProfile(
        workspace_id=uuid4(),
        account_id=uuid4(),
        scope_key="account",
        version=1,
        status=StyleProfileStatus.CONFIRMED,
        style={
            "title": {"hooks": ["history-title"]},
            "copy": {"tones": ["history-copy"]},
            "cover": {"colors": ["history-cover"]},
            "prohibited": {
                "expressions": ["history-expression"],
                "colors": ["history-color"],
                "layouts": ["history-layout"],
                "visual_styles": ["history-visual"],
            },
        },
        sample_content_ids=[],
        diff={},
    )

    without_cover = StyleProfileService.filtered_style(
        profile,
        StyleInheritanceSwitches(title=True, copy=True, cover=False),
    )
    assert without_cover["prohibited"] == {
        "expressions": ["history-expression"]
    }

    cover_only = StyleProfileService.filtered_style(
        profile,
        StyleInheritanceSwitches(title=False, copy=False, cover=True),
    )
    assert cover_only["prohibited"] == {
        "colors": ["history-color"],
        "layouts": ["history-layout"],
        "visual_styles": ["history-visual"],
    }
