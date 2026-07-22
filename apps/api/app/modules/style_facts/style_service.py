from collections import Counter
from collections.abc import Iterable
from datetime import datetime
import re
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utc_now
from app.core.security import WorkspaceContext
from app.modules.content.account_models import ColumnCampaign, PlatformAccount
from app.modules.content.models import AssetCategory, Content, ContentAsset, ContentStatus
from app.modules.style_facts.style_models import (
    AccountStyleProfile,
    StyleProfileStatus,
    StyleSample,
)
from app.modules.workspace.models import AuditLog
from app.modules.workspace.permissions import Permission, require_permission


class LengthRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: int = Field(ge=0, le=300)
    maximum: int = Field(ge=0, le=300)


class TitleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    length: LengthRange
    sentence_patterns: list[str]
    hooks: list[str]
    frequent_words: list[str]
    punctuation: list[str]
    emojis: list[str]


class CopyStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tones: list[str]
    openings: list[str]
    paragraph_structure: list[str]
    information_density: str
    calls_to_action: list[str]


class CoverStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    colors: list[str]
    fonts: list[str]
    size_hierarchy: list[str]
    text_positions: list[str]
    logos: list[str]
    compositions: list[str]
    whitespace: list[str]


class ProhibitedStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expressions: list[str]
    colors: list[str]
    layouts: list[str]
    visual_styles: list[str]


class StyleDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    title: TitleStyle
    copy_style: CopyStyle = Field(alias="copy")
    cover: CoverStyle
    prohibited: ProhibitedStyle


class StyleInheritanceSwitches(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    title: bool = True
    copy_style: bool = Field(default=True, alias="copy")
    cover: bool = True


class StyleProfileRequired(LookupError):
    code = "STYLE_PROFILE_REQUIRED"

    def __init__(self) -> None:
        super().__init__("请先提取并确认账号风格档案")


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class StyleProfileService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _account(
        self, account_id: UUID, *, lock: bool = False
    ) -> PlatformAccount:
        query = select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        if lock:
            query = query.with_for_update()
        account = self._session.scalar(query)
        if account is None:
            raise LookupError("account not found")
        return account

    def _column(
        self,
        account_id: UUID,
        column_campaign_id: UUID,
    ) -> ColumnCampaign:
        column = self._session.scalar(
            select(ColumnCampaign).where(
                ColumnCampaign.id == column_campaign_id,
                ColumnCampaign.workspace_id == self._context.workspace_id,
                ColumnCampaign.account_id == account_id,
            )
        )
        if column is None:
            raise LookupError("column or campaign not found")
        return column

    def select_sample(
        self,
        account_id: UUID,
        content_id: UUID,
        column_campaign_id: UUID | None = None,
    ) -> StyleSample:
        require_permission(self._context.role, Permission.MANAGE_STYLES)
        self._account(account_id)
        if column_campaign_id is not None:
            self._column(account_id, column_campaign_id)
        scope_key = (
            f"column:{column_campaign_id}" if column_campaign_id else "account"
        )
        content = self._session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == self._context.workspace_id,
                Content.account_id == account_id,
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise LookupError("content not found")
        if content.status is not ContentStatus.PUBLISHED:
            raise ValueError("only published content can be selected")
        existing = self._session.scalar(
            select(StyleSample).where(
                StyleSample.workspace_id == self._context.workspace_id,
                StyleSample.account_id == account_id,
                StyleSample.scope_key == scope_key,
                StyleSample.content_id == content_id,
            )
        )
        if existing is not None:
            return existing
        sample = StyleSample(
            workspace_id=self._context.workspace_id,
            account_id=account_id,
            scope_key=scope_key,
            content_id=content_id,
            column_campaign_id=column_campaign_id,
            selected_by=self._context.member_id,
        )
        self._session.add(sample)
        self._session.flush()
        return sample

    def list_samples(
        self,
        account_id: UUID,
        column_campaign_id: UUID | None = None,
    ) -> list[tuple[StyleSample, Content]]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        if column_campaign_id is not None:
            self._column(account_id, column_campaign_id)
        scope_key = (
            f"column:{column_campaign_id}" if column_campaign_id else "account"
        )
        return list(
            self._session.execute(
                select(StyleSample, Content)
                .join(Content, Content.id == StyleSample.content_id)
                .where(
                    StyleSample.workspace_id == self._context.workspace_id,
                    StyleSample.account_id == account_id,
                    StyleSample.scope_key == scope_key,
                    Content.status == ContentStatus.PUBLISHED,
                    Content.deleted_at.is_(None),
                )
                .order_by(StyleSample.selected_at, StyleSample.id)
            ).tuples()
        )

    def candidate_contents(
        self,
        account_id: UUID,
        column_campaign_id: UUID | None = None,
    ) -> list[tuple[Content, bool]]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        if column_campaign_id is not None:
            self._column(account_id, column_campaign_id)
        scope_key = (
            f"column:{column_campaign_id}" if column_campaign_id else "account"
        )
        selected_ids = set(
            self._session.scalars(
                select(StyleSample.content_id).where(
                    StyleSample.workspace_id == self._context.workspace_id,
                    StyleSample.account_id == account_id,
                    StyleSample.scope_key == scope_key,
                )
            )
        )
        contents = self._session.scalars(
            select(Content)
            .where(
                Content.workspace_id == self._context.workspace_id,
                Content.account_id == account_id,
                Content.status == ContentStatus.PUBLISHED,
                Content.deleted_at.is_(None),
            )
            .order_by(Content.published_at.desc(), Content.id)
        )
        return [(content, content.id in selected_ids) for content in contents]

    @staticmethod
    def _extract_style(
        contents: list[Content],
        cover_assets: list[ContentAsset],
        prohibited: ProhibitedStyle | None,
    ) -> StyleDocument:
        titles = [content.published_title or content.title for content in contents]
        bodies = [content.published_body or content.body for content in contents]
        lengths = [len(title) for title in titles]
        punctuation = _unique(
            character
            for title in titles
            for character in title
            if character in "，。！？：；、,.!?:;"
        )
        emojis = _unique(
            character
            for title in titles
            for character in title
            if ord(character) > 0x1F000
        )
        words = Counter(
            token.lower()
            for title in titles
            for token in re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,4}", title)
        )
        hooks = _unique(
            title.split("：", 1)[0]
            for title in titles
            if "：" in title
        )
        calls_to_action = _unique(
            phrase
            for body in bodies
            for phrase in ("马上收藏", "立即查看", "评论区告诉我")
            if phrase in body
        )
        cover_tags = {
            tag
            for asset in cover_assets
            for tag in asset.file_name.rsplit(".", 1)[0].lower().split("__")
        }

        def cover_tokens(*tokens: str) -> list[str]:
            return [token for token in tokens if token in cover_tags]

        return StyleDocument(
            title=TitleStyle(
                length=LengthRange(minimum=min(lengths), maximum=max(lengths)),
                sentence_patterns=_unique(
                    "question" if "？" in title else "statement" for title in titles
                ),
                hooks=hooks,
                frequent_words=[word for word, _ in words.most_common(10)],
                punctuation=punctuation,
                emojis=emojis,
            ),
            copy=CopyStyle(
                tones=["direct" if any("！" in body for body in bodies) else "neutral"],
                openings=_unique(body.split("。", 1)[0] for body in bodies),
                paragraph_structure=["short_paragraphs"],
                information_density="medium",
                calls_to_action=calls_to_action,
            ),
            cover=CoverStyle(
                colors=cover_tokens("cyan", "red", "blue", "green", "black", "white"),
                fonts=cover_tokens("sans", "serif", "heiti", "songti"),
                size_hierarchy=cover_tokens("title-large", "balanced", "caption-led"),
                text_positions=cover_tokens("top-left", "top-center", "center", "bottom"),
                logos=cover_tokens("brand-logo", "corner-logo"),
                compositions=cover_tokens("subject-right", "subject-left", "centered"),
                whitespace=cover_tokens("generous", "compact"),
            ),
            prohibited=prohibited
            or ProhibitedStyle(
                expressions=[], colors=[], layouts=[], visual_styles=[]
            ),
        )

    def extract_profile(
        self,
        account_id: UUID,
        column_campaign_id: UUID | None = None,
        prohibited: ProhibitedStyle | None = None,
    ) -> AccountStyleProfile:
        require_permission(self._context.role, Permission.MANAGE_STYLES)
        self._account(account_id, lock=True)
        if column_campaign_id is not None:
            self._column(account_id, column_campaign_id)
        samples = self.list_samples(account_id, column_campaign_id)
        if not samples:
            raise ValueError("select at least one published style sample")
        contents = [content for _, content in samples]
        cover_assets = list(
            self._session.scalars(
                select(ContentAsset)
                .where(
                    ContentAsset.workspace_id == self._context.workspace_id,
                    ContentAsset.content_id.in_(content.id for content in contents),
                    ContentAsset.category == AssetCategory.COVER,
                )
                .order_by(ContentAsset.content_id, ContentAsset.id)
            )
        )
        scope_key = (
            f"column:{column_campaign_id}" if column_campaign_id else "account"
        )
        previous = self._session.scalar(
            select(AccountStyleProfile)
            .where(
                AccountStyleProfile.workspace_id == self._context.workspace_id,
                AccountStyleProfile.account_id == account_id,
                AccountStyleProfile.scope_key == scope_key,
                AccountStyleProfile.status == StyleProfileStatus.CONFIRMED,
            )
            .order_by(AccountStyleProfile.version.desc())
            .limit(1)
        )
        latest_version = self._session.scalar(
            select(func.max(AccountStyleProfile.version)).where(
                AccountStyleProfile.workspace_id == self._context.workspace_id,
                AccountStyleProfile.account_id == account_id,
                AccountStyleProfile.scope_key == scope_key,
            )
        )
        if prohibited is None and previous is not None:
            prohibited = ProhibitedStyle.model_validate(previous.style["prohibited"])
        style = self._extract_style(contents, cover_assets, prohibited).model_dump(
            mode="json", by_alias=True
        )
        changed_sections = [
            section
            for section in style
            if previous is None or previous.style.get(section) != style[section]
        ]
        profile = AccountStyleProfile(
            workspace_id=self._context.workspace_id,
            account_id=account_id,
            scope_key=scope_key,
            version=(latest_version or 0) + 1,
            status=StyleProfileStatus.PENDING_CONFIRMATION,
            style=style,
            sample_content_ids=[str(content.id) for content in contents],
            diff={
                "base_version": previous.version if previous else None,
                "changed_sections": changed_sections,
            },
            column_campaign_id=column_campaign_id,
            base_profile_id=previous.id if previous else None,
            created_by=self._context.member_id,
        )
        self._session.add(profile)
        self._session.flush()
        return profile

    def confirm_profile(self, profile_id: UUID) -> AccountStyleProfile:
        require_permission(self._context.role, Permission.MANAGE_STYLES)
        profile = self._session.scalar(
            select(AccountStyleProfile).where(
                AccountStyleProfile.id == profile_id,
                AccountStyleProfile.workspace_id == self._context.workspace_id,
            )
        )
        if profile is None:
            raise LookupError("style profile not found")
        if profile.status is StyleProfileStatus.CONFIRMED:
            return profile
        profile.status = StyleProfileStatus.CONFIRMED
        profile.confirmed_by = self._context.member_id
        profile.confirmed_at = utc_now()
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                action="style_profile.confirmed",
                resource_type="account_style_profile",
                resource_id=profile.id,
                member_id=self._context.member_id,
                details={
                    "account_id": str(profile.account_id),
                    "version": profile.version,
                    "scope": profile.scope_key,
                },
            )
        )
        self._session.flush()
        return profile

    def list_profiles(self, account_id: UUID) -> list[AccountStyleProfile]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        return list(
            self._session.scalars(
                select(AccountStyleProfile)
                .where(
                    AccountStyleProfile.workspace_id == self._context.workspace_id,
                    AccountStyleProfile.account_id == account_id,
                )
                .order_by(AccountStyleProfile.created_at, AccountStyleProfile.id)
            )
        )

    def effective_profile(
        self,
        account_id: UUID,
        *,
        column_campaign_id: UUID | None = None,
        at: datetime | None = None,
    ) -> tuple[AccountStyleProfile, str]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._account(account_id)
        moment = at or utc_now()
        scope_key = "account"
        source = "account_default"
        if column_campaign_id is not None:
            column = self._column(account_id, column_campaign_id)
            active = (
                (column.starts_at is None or moment >= column.starts_at)
                and (column.ends_at is None or moment <= column.ends_at)
            )
            if active:
                scope_key = f"column:{column_campaign_id}"
                source = "column_override"
        profile = self._session.scalar(
            select(AccountStyleProfile)
            .where(
                AccountStyleProfile.workspace_id == self._context.workspace_id,
                AccountStyleProfile.account_id == account_id,
                AccountStyleProfile.scope_key == scope_key,
                AccountStyleProfile.status == StyleProfileStatus.CONFIRMED,
            )
            .order_by(AccountStyleProfile.version.desc())
            .limit(1)
        )
        if profile is None and scope_key != "account":
            source = "account_default"
            profile = self._session.scalar(
                select(AccountStyleProfile)
                .where(
                    AccountStyleProfile.workspace_id == self._context.workspace_id,
                    AccountStyleProfile.account_id == account_id,
                    AccountStyleProfile.scope_key == "account",
                    AccountStyleProfile.status == StyleProfileStatus.CONFIRMED,
                )
                .order_by(AccountStyleProfile.version.desc())
                .limit(1)
            )
        if profile is None:
            raise StyleProfileRequired()
        return profile, source

    @staticmethod
    def filtered_style(
        profile: AccountStyleProfile,
        switches: StyleInheritanceSwitches,
    ) -> dict[str, object]:
        style: dict[str, object] = {}
        for section, enabled in (
            ("title", switches.title),
            ("copy", switches.copy_style),
            ("cover", switches.cover),
        ):
            if enabled:
                style[section] = profile.style[section]
        prohibited = cast(dict[str, object], profile.style["prohibited"])
        filtered_prohibited: dict[str, object] = {}
        if switches.title or switches.copy_style:
            filtered_prohibited["expressions"] = prohibited["expressions"]
        if switches.cover:
            for key in ("colors", "layouts", "visual_styles"):
                filtered_prohibited[key] = prohibited[key]
        if filtered_prohibited:
            style["prohibited"] = filtered_prohibited
        return style
