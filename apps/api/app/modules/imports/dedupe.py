from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.content.account_models import Platform
from app.modules.content.models import Content
from app.modules.imports.models import ImportRowStatus


def classify_duplicate(
    session: Session,
    *,
    workspace_id: UUID,
    account_id: UUID,
    platform: Platform,
    normalized_data: dict[str, object],
) -> tuple[ImportRowStatus, UUID | None, str | None]:
    scope = (
        Content.workspace_id == workspace_id,
        Content.account_id == account_id,
        Content.platform == platform,
        Content.deleted_at.is_(None),
    )
    platform_content_id = normalized_data.get("platform_content_id")
    work_url = normalized_data.get("work_url")
    exact_conditions = []
    if platform_content_id:
        exact_conditions.append(Content.platform_content_id == platform_content_id)
    if work_url:
        exact_conditions.append(Content.work_url == work_url)
    if exact_conditions:
        existing = session.scalar(
            select(Content).where(*scope, or_(*exact_conditions)).limit(1)
        )
        if existing is not None:
            return ImportRowStatus.UPDATE, existing.id, "same_platform_id_or_url"
        return ImportRowStatus.NEW, None, None

    title = normalized_data.get("title")
    published_at = normalized_data.get("published_at")
    if title and published_at:
        candidate = session.scalar(
            select(Content)
            .where(
                *scope,
                Content.title == title,
                Content.published_at == datetime.fromisoformat(str(published_at)),
            )
            .limit(1)
        )
        if candidate is not None:
            return (
                ImportRowStatus.SUSPECTED_DUPLICATE,
                candidate.id,
                "same_title_and_published_at",
            )
    return ImportRowStatus.NEW, None, None
