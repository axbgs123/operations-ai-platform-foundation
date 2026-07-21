from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import ColumnCampaign, Platform, PlatformAccount
from app.modules.content.account_service import AccountConfigurationService
from app.modules.content.models import AssetCategory, Content, ContentAsset, ContentStatus, DeletedItem
from app.modules.workspace.models import AuditLog
from app.modules.workspace.permissions import Permission, require_permission


class ContentService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

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
            content.status = ContentStatus.PUBLISHED
            content.published_title = content.title
            content.published_body = content.body
            content.published_at = datetime.now(UTC)
            self._audit("content.published", content.id)
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
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        content = self._get(content_id)
        content.deleted_at = datetime.now(UTC)
        self._session.add(
            DeletedItem(
                workspace_id=self._context.workspace_id,
                resource_type="content",
                resource_id=content.id,
                deleted_by=self._context.member_id,
            )
        )
        self._audit("content.deleted", content.id)
        self._session.flush()

    def restore(self, content_id: UUID) -> Content:
        content = self._get(content_id, include_deleted=True)
        if content.deleted_at is None:
            raise ValueError("content is not deleted")
        content.deleted_at = None
        deleted_item = self._session.scalar(
            select(DeletedItem)
            .where(
                DeletedItem.workspace_id == self._context.workspace_id,
                DeletedItem.resource_type == "content",
                DeletedItem.resource_id == content.id,
                DeletedItem.restored_at.is_(None),
            )
            .order_by(DeletedItem.deleted_at.desc())
        )
        if deleted_item is not None:
            deleted_item.restored_at = datetime.now(UTC)
        self._audit("content.restored", content.id)
        self._session.flush()
        return content

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
