from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.content.models import AssetCategory, ContentAsset
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember
from tests.imports.helpers import configured_client
from tests.style_facts.helpers import (
    confirm_profile,
    draft_content,
    extract_profile,
    published_content,
    select_sample,
    style_workspace,
)


def test_style_task_context_restores_real_active_member_role_and_scope() -> None:
    from app.modules.style_facts.style_tasks import resolve_style_task_context

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="任务权限工作区")
        other_workspace = Workspace(name="其他工作区")
        session.add_all([workspace, other_workspace])
        session.flush()
        editor = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="风格编辑",
            role=MemberRole.EDITOR,
        )
        revoked = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="已撤销成员",
            role=MemberRole.ADMIN,
        )
        session.add_all([editor, revoked])
        session.flush()
        revoked.revoked_at = revoked.created_at
        session.flush()

        context = resolve_style_task_context(session, workspace.id, editor.id)
        assert context.workspace_id == workspace.id
        assert context.member_id == editor.id
        assert context.role == "editor"

        for target_workspace, member_id in (
            (other_workspace.id, editor.id),
            (workspace.id, revoked.id),
        ):
            try:
                resolve_style_task_context(session, target_workspace, member_id)
            except LookupError as error:
                assert "active member" in str(error)
            else:
                raise AssertionError("task context must preserve membership boundaries")


def test_only_explicitly_selected_published_content_becomes_a_style_sample() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        draft = draft_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="草稿不能成为样本",
        )
        recent = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="最近发布但未人工选择",
        )
        selected = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="人工选择：三步看懂 AI！✨",
        )

        rejected = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-samples",
            headers={"X-CSRF-Token": csrf},
            json={"content_id": draft["id"]},
        )
        assert rejected.status_code == 422
        assert "published" in rejected.text

        sample = select_sample(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            content_id=selected["id"],
            csrf=csrf,
        )
        assert sample["content_id"] == selected["id"]
        assert sample["title"] == selected["published_title"]
        assert sample["selected_by"]

        samples = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-samples"
        )
        assert samples.status_code == 200
        assert [item["content_id"] for item in samples.json()] == [selected["id"]]
        assert recent["id"] not in {item["content_id"] for item in samples.json()}


def test_recent_or_viral_eligible_content_is_never_auto_selected() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="即使表现优秀也不能自动成为品牌风格",
        )

        response = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-profiles/extract",
            headers={"X-CSRF-Token": csrf},
            json={"column_campaign_id": None},
        )

        assert response.status_code == 422
        assert "select" in response.text.lower()


def test_archived_or_deleted_selected_content_is_excluded_from_new_profiles() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        archived = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="之后归档的样本",
        )
        deleted = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="之后删除的样本",
        )
        for content in (archived, deleted):
            select_sample(
                client,
                workspace_id=workspace_id,
                account_id=account["id"],
                content_id=content["id"],
                csrf=csrf,
            )
        archived_response = client.patch(
            f"/v1/contents/{archived['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "archived"},
        )
        assert archived_response.status_code == 200, archived_response.text
        deleted_response = client.delete(
            f"/v1/contents/{deleted['id']}",
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted_response.status_code == 204, deleted_response.text

        extraction = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-profiles/extract",
            headers={"X-CSRF-Token": csrf},
            json={"column_campaign_id": None},
        )
        assert extraction.status_code == 422
        assert "select" in extraction.text.lower()


def test_extraction_creates_complete_pending_immutable_versions_until_confirmed() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        first_content = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="先看结论：AI 工具效率翻倍！✨",
            body="先说结论。三个步骤，马上收藏。",
        )
        select_sample(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            content_id=first_content["id"],
            csrf=csrf,
        )

        first = extract_profile(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )
        assert first["version"] == 1
        assert first["scope_key"] == "account"
        assert first["status"] == "pending_confirmation"
        assert first["sample_sources"][0]["content_id"] == first_content["id"]
        assert set(first["style"]) == {"title", "copy", "cover", "prohibited"}
        assert set(first["style"]["title"]) == {
            "length",
            "sentence_patterns",
            "hooks",
            "frequent_words",
            "punctuation",
            "emojis",
        }
        assert set(first["style"]["copy"]) == {
            "tones",
            "openings",
            "paragraph_structure",
            "information_density",
            "calls_to_action",
        }
        assert set(first["style"]["cover"]) == {
            "colors",
            "fonts",
            "size_hierarchy",
            "text_positions",
            "logos",
            "compositions",
            "whitespace",
        }
        assert set(first["style"]["prohibited"]) == {
            "expressions",
            "colors",
            "layouts",
            "visual_styles",
        }

        before_confirmation = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/effective-style"
        )
        assert before_confirmation.status_code == 409
        assert before_confirmation.json()["detail"]["code"] == "STYLE_PROFILE_REQUIRED"

        confirmed_first = confirm_profile(
            client,
            workspace_id=workspace_id,
            profile_id=first["id"],
            csrf=csrf,
        )
        assert confirmed_first["status"] == "confirmed"
        frozen_first_style = confirmed_first["style"]

        second_content = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="别再低效：五个自动化技巧？",
            body="别再重复劳动。五个技巧，评论区告诉我你的选择。",
        )
        select_sample(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            content_id=second_content["id"],
            csrf=csrf,
        )
        second = extract_profile(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )
        assert second["version"] == 2
        assert second["diff"]["base_version"] == 1
        assert second["diff"]["changed_sections"]

        history = client.get(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-profiles"
        )
        assert history.status_code == 200
        assert [item["version"] for item in history.json()] == [1, 2]
        assert history.json()[0]["style"] == frozen_first_style


def test_cover_metadata_and_explicit_prohibitions_produce_meaningful_profile_fields() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = style_workspace(client)
        content = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="具有可验证封面元数据的内容",
        )
        with Session(engine) as session:
            session.add_all([
                ContentAsset(
                    workspace_id=UUID(content["workspace_id"]),
                    content_id=UUID(content["id"]),
                    category=AssetCategory.COVER,
                    object_key=f"synthetic/{content['id']}/cyan-cover.png",
                    file_name=(
                        "cyan__sans__title-large__top-left__brand-logo__"
                        "subject-right__generous.png"
                    ),
                    mime_type="image/png",
                    size=2048,
                ),
                ContentAsset(
                    workspace_id=UUID(content["workspace_id"]),
                    content_id=UUID(content["id"]),
                    category=AssetCategory.COVER,
                    object_key=f"synthetic/{content['id']}/deceptive-cover.png",
                    file_name="centered__redesign.png",
                    mime_type="image/png",
                    size=1024,
                ),
            ])
            session.commit()
        select_sample(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            content_id=content["id"],
            csrf=csrf,
        )

        response = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-profiles/extract",
            headers={"X-CSRF-Token": csrf},
            json={
                "column_campaign_id": None,
                "prohibited": {
                    "expressions": ["绝对第一"],
                    "colors": ["neon-red"],
                    "layouts": ["dense-grid"],
                    "visual_styles": ["low-contrast"],
                },
            },
        )

        assert response.status_code == 201, response.text
        style = response.json()["style"]
        assert style["cover"] == {
            "colors": ["cyan"],
            "fonts": ["sans"],
            "size_hierarchy": ["title-large"],
            "text_positions": ["top-left"],
            "logos": ["brand-logo"],
            "compositions": ["subject-right", "centered"],
            "whitespace": ["generous"],
        }
        assert style["prohibited"] == {
            "expressions": ["绝对第一"],
            "colors": ["neon-red"],
            "layouts": ["dense-grid"],
            "visual_styles": ["low-contrast"],
        }


def test_reextraction_preserves_prohibitions_unless_explicitly_cleared() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = style_workspace(client)
        content = published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="保留显式禁止项的样本",
        )
        select_sample(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            content_id=content["id"],
            csrf=csrf,
        )
        prohibited = {
            "expressions": ["绝对第一"],
            "colors": ["neon-red"],
            "layouts": ["dense-grid"],
            "visual_styles": ["low-contrast"],
        }
        first_response = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-profiles/extract",
            headers={"X-CSRF-Token": csrf},
            json={"column_campaign_id": None, "prohibited": prohibited},
        )
        assert first_response.status_code == 201, first_response.text
        confirm_profile(
            client,
            workspace_id=workspace_id,
            profile_id=first_response.json()["id"],
            csrf=csrf,
        )

        preserved = extract_profile(
            client,
            workspace_id=workspace_id,
            account_id=account["id"],
            csrf=csrf,
        )
        assert preserved["style"]["prohibited"] == prohibited

        cleared_response = client.post(
            f"/v1/workspaces/{workspace_id}/accounts/{account['id']}/style-profiles/extract",
            headers={"X-CSRF-Token": csrf},
            json={
                "column_campaign_id": None,
                "prohibited": {
                    "expressions": [],
                    "colors": [],
                    "layouts": [],
                    "visual_styles": [],
                },
            },
        )
        assert cleared_response.status_code == 201, cleared_response.text
        assert cleared_response.json()["style"]["prohibited"] == {
            "expressions": [],
            "colors": [],
            "layouts": [],
            "visual_styles": [],
        }
