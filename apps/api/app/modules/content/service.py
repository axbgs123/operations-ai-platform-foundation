from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analytics.events import EventName, EventService, ProductEventInput
from app.modules.content.account_models import ColumnCampaign, Platform, PlatformAccount
from app.modules.content.account_service import AccountConfigurationService
from app.modules.content.models import AssetCategory, Content, ContentAsset, ContentStatus
from app.modules.metrics.models import ContentType
from app.modules.metrics.models import DataSnapshot
from app.modules.workspace.models import AuditLog
from app.modules.workspace.permissions import Permission, require_permission


class ContentService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    @property
    def context(self) -> WorkspaceContext:
        return self._context

    def _get(self, content_id: UUID, *, include_deleted: bool = False) -> Content:
        statement = select(Content).where(
            Content.id == content_id,
            Content.workspace_id == self._context.workspace_id,
        )
        if not include_deleted:
            statement = statement.where(Content.deleted_at.is_(None))
        content = self._session.scalar(statement)
        if content is None:
            raise LookupError("content not found")
        return content

    def create(
        self,
        *,
        account_id: UUID,
        platform: Platform,
        content_type: ContentType,
        title: str,
        body: str,
        column_campaign_id: UUID | None,
        work_url: str | None,
    ) -> Content:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("account not found")
        if account.platform != platform:
            raise ValueError("content platform must match account platform")
        if column_campaign_id is not None:
            item = self._session.scalar(
                select(ColumnCampaign).where(
                    ColumnCampaign.id == column_campaign_id,
                    ColumnCampaign.account_id == account.id,
                    ColumnCampaign.workspace_id == self._context.workspace_id,
                )
            )
            if item is None:
                raise ValueError("column or campaign must belong to the account")
        effective = AccountConfigurationService(
            self._session, self._context
        ).effective_configuration(
            account.id,
            column_campaign_id=column_campaign_id,
            at=datetime.now(UTC),
        )
        content = Content(
            workspace_id=self._context.workspace_id,
            account_id=account.id,
            platform=platform,
            content_type=content_type,
            title=title,
            body=body,
            objective_profile_id=effective.objective_profile.id,
            benchmark_profile_id=effective.benchmark_profile.id,
            column_campaign_id=column_campaign_id,
            work_url=work_url,
        )
        self._session.add(content)
        self._session.flush()
        self._audit("content.created", content.id)
        return content

    def read(self, content_id: UUID) -> Content:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return self._get(content_id)

    def prepare_asset(self, content_id: UUID, category: AssetCategory) -> Content:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        content = self._get(content_id)
        limits = {
            AssetCategory.COVER: 1,
            AssetCategory.SCREENSHOT: 20,
            AssetCategory.REFERENCE_IMAGE: 5,
            AssetCategory.DOCUMENT: 5,
        }
        existing = list(
            self._session.scalars(
                select(ContentAsset).where(
                    ContentAsset.content_id == content.id,
                    ContentAsset.category == category,
                )
            )
        )
        if len(existing) >= limits[category]:
            raise ValueError(f"{category.value} asset limit reached")
        return content

    def confirm_asset(
        self,
        content_id: UUID,
        *,
        category: AssetCategory,
        object_key: str,
        file_name: str,
        mime_type: str,
        size: int,
    ) -> ContentAsset:
        content = self.prepare_asset(content_id, category)
        asset = ContentAsset(
            workspace_id=self._context.workspace_id,
            content_id=content.id,
            category=category,
            object_key=object_key,
            file_name=file_name,
            mime_type=mime_type,
            size=size,
        )
        self._session.add(asset)
        self._session.flush()
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                member_id=self._context.member_id,
                action="content.asset_confirmed",
                resource_type="content_asset",
                resource_id=asset.id,
                details={"content_id": str(content.id), "category": category.value},
            )
        )
        self._session.flush()
        return asset

    def list(self, *, trash: bool) -> list[Content]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        condition = Content.deleted_at.is_not(None) if trash else Content.deleted_at.is_(None)
        return list(
            self._session.scalars(
                select(Content)
                .where(Content.workspace_id == self._context.workspace_id, condition)
                .order_by(Content.created_at)
            )
        )

    def list_page(
        self,
        *,
        platform: Platform | None,
        account_id: UUID | None,
        column_id: UUID | None,
        content_type: ContentType | None,
        status: ContentStatus | None,
        maturity: str | None,
        query: str | None,
        sort: str,
        page: int,
        page_size: int,
        allowed_content_ids: set[UUID] | None = None,
    ) -> tuple[Sequence[Content], int]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        if account_id is not None:
            account = self._session.scalar(
                select(PlatformAccount).where(
                    PlatformAccount.id == account_id,
                    PlatformAccount.workspace_id == self._context.workspace_id,
                )
            )
            if account is None or (platform is not None and account.platform != platform):
                raise LookupError("account not found")
        if column_id is not None:
            column = self._session.scalar(
                select(ColumnCampaign).where(
                    ColumnCampaign.id == column_id,
                    ColumnCampaign.workspace_id == self._context.workspace_id,
                )
            )
            if (
                column is None
                or (account_id is not None and column.account_id != account_id)
            ):
                raise LookupError("column or campaign not found")
            column_account = self._session.scalar(
                select(PlatformAccount).where(
                    PlatformAccount.id == column.account_id,
                    PlatformAccount.workspace_id == self._context.workspace_id,
                )
            )
            if (
                column_account is None
                or (platform is not None and column_account.platform != platform)
            ):
                raise LookupError("column or campaign not found")

        conditions = [
            Content.workspace_id == self._context.workspace_id,
            Content.deleted_at.is_(None),
        ]
        if allowed_content_ids is not None:
            conditions.append(Content.id.in_(allowed_content_ids))
        if platform is not None:
            conditions.append(Content.platform == platform)
        if account_id is not None:
            conditions.append(Content.account_id == account_id)
        if column_id is not None:
            conditions.append(Content.column_campaign_id == column_id)
        if content_type is not None:
            conditions.append(Content.content_type == content_type)
        if status is not None:
            conditions.append(Content.status == status)
        if query:
            escaped = (
                query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            conditions.append(Content.title.ilike(f"%{escaped}%", escape="\\"))
        if maturity is not None:
            latest_maturity = (
                select(DataSnapshot.maturity_bucket)
                .where(
                    DataSnapshot.workspace_id == self._context.workspace_id,
                    DataSnapshot.content_id == Content.id,
                    DataSnapshot.confirmed.is_(True),
                )
                .order_by(
                    DataSnapshot.collected_at.desc(),
                    DataSnapshot.id.desc(),
                )
                .limit(1)
                .scalar_subquery()
            )
            conditions.append(latest_maturity == maturity)

        total = self._session.scalar(
            select(func.count()).select_from(Content).where(*conditions)
        ) or 0
        statement = select(Content).where(*conditions)
        if sort == "newest":
            statement = statement.order_by(
                Content.created_at.desc(),
                Content.id.desc(),
            )
        elif sort == "oldest":
            statement = statement.order_by(
                Content.created_at.asc(),
                Content.id.asc(),
            )
        elif sort == "title_asc":
            statement = statement.order_by(Content.title.asc(), Content.id.asc())
        elif sort == "title_desc":
            statement = statement.order_by(
                Content.title.desc(),
                Content.id.desc(),
            )
        else:
            statement = statement.order_by(
                Content.published_at.desc().nulls_last(),
                Content.id.desc(),
            )
        items = list(
            self._session.scalars(
                statement.offset((page - 1) * page_size).limit(page_size)
            )
        )
        return items, total

    def update(
        self,
        content_id: UUID,
        *,
        changes: dict,
    ) -> Content:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        if changes.get("restore"):
            return self.restore(content_id)
        content = self._get(content_id)
        if "column_campaign_id" in changes:
            if content.status != ContentStatus.DRAFT:
                raise ValueError("published content cannot change column or campaign")
            column_campaign_id = changes["column_campaign_id"]
            if column_campaign_id is not None:
                item = self._session.scalar(
                    select(ColumnCampaign).where(
                        ColumnCampaign.id == column_campaign_id,
                        ColumnCampaign.account_id == content.account_id,
                        ColumnCampaign.workspace_id == self._context.workspace_id,
                    )
                )
                if item is None:
                    raise ValueError("column or campaign must belong to the account")
            effective = AccountConfigurationService(
                self._session, self._context
            ).effective_configuration(
                content.account_id,
                column_campaign_id=column_campaign_id,
                at=datetime.now(UTC),
            )
            content.column_campaign_id = column_campaign_id
            content.objective_profile_id = effective.objective_profile.id
            content.benchmark_profile_id = effective.benchmark_profile.id
        for field in ("title", "body", "work_url"):
            if field in changes:
                setattr(content, field, changes[field])
        status = changes.get("status")
        if status == "published":
            was_published = content.published_at is not None
            content.status = ContentStatus.PUBLISHED
            content.published_title = content.title
            content.published_body = content.body
            content.published_at = datetime.now(UTC)
            self._audit("content.published", content.id)
            if not was_published:
                EventService(self._session, self._context).record(
                    ProductEventInput(
                        event_name=EventName.CONTENT_PUBLISHED,
                        idempotency_key=f"content-published:{content.id}",
                        account_id=content.account_id,
                        content_id=content.id,
                        properties={"content_version": "content-v1"},
                    )
                )
        elif status == "archived":
            if content.status != ContentStatus.PUBLISHED:
                raise ValueError("only published content can be archived")
            content.status = ContentStatus.ARCHIVED
            self._audit("content.archived", content.id)
        else:
            self._audit("content.updated", content.id)
        self._session.flush()
        return content

    def delete(self, content_id: UUID) -> None:
        from app.modules.exports.deletion import TrashService

        TrashService(
            self._session,
            self._context,
        ).soft_delete_content(content_id)

    def restore(self, content_id: UUID) -> Content:
        from app.modules.exports.deletion import TrashService

        return TrashService(
            self._session,
            self._context,
        ).restore_content(content_id)

    def _audit(self, action: str, resource_id: UUID) -> None:
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                member_id=self._context.member_id,
                action=action,
                resource_type="content",
                resource_id=resource_id,
            )
        )
