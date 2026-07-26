import csv
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.models import Content
from app.modules.metrics.models import DataSnapshot, SnapshotMetricValue


CSV_FIELDS = (
    "content_id",
    "account_id",
    "platform",
    "content_type",
    "platform_content_id",
    "title",
    "body",
    "status",
    "work_url",
    "published_at",
    "snapshot_id",
    "collected_at",
    "source",
    "metric_key",
    "raw_value",
    "normalized_value",
    "ocr_confidence",
)
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def isoformat_preserving_timezone(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        raise ValueError("exported datetime must include a timezone")
    return value.isoformat()


def safe_export_filename(label: str, extension: str) -> str:
    safe_extension = re.sub(r"[^a-z0-9]", "", extension.lower())
    if not safe_extension:
        raise ValueError("file extension is required")
    normalized = unicodedata.normalize("NFKC", label)
    normalized = re.sub(r"[/\\\r\n:\x00-\x1f\x7f]+", "-", normalized)
    normalized = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", normalized, flags=re.UNICODE)
    normalized = normalized.strip(" .-_")[:120] or "export"
    return f"{normalized}.{safe_extension}"


def formula_safe_cell(value: str) -> str:
    if value.lstrip().startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _string_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return formula_safe_cell(value)
    if isinstance(value, datetime):
        rendered = isoformat_preserving_timezone(value)
    elif isinstance(value, Decimal):
        rendered = format(value, "f")
    else:
        rendered = str(value)
    return rendered


def render_workspace_csv(
    session: Session,
    context: WorkspaceContext,
    *,
    heartbeat: Callable[[], None] | None = None,
) -> bytes:
    contents = list(
        session.scalars(
            select(Content)
            .where(
                Content.workspace_id == context.workspace_id,
                Content.deleted_at.is_(None),
            )
            .order_by(Content.created_at, Content.id)
        )
    )
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for content in contents:
        if heartbeat is not None:
            heartbeat()
        snapshots = list(
            session.scalars(
                select(DataSnapshot)
                .where(
                    DataSnapshot.workspace_id == context.workspace_id,
                    DataSnapshot.content_id == content.id,
                    DataSnapshot.platform == content.platform,
                    DataSnapshot.content_type == content.content_type,
                )
                .order_by(DataSnapshot.collected_at, DataSnapshot.id)
            )
        )
        if not snapshots:
            writer.writerow(_row(content))
            continue
        for snapshot in snapshots:
            values = list(
                session.scalars(
                    select(SnapshotMetricValue)
                    .where(
                        SnapshotMetricValue.workspace_id == context.workspace_id,
                        SnapshotMetricValue.snapshot_id == snapshot.id,
                    )
                    .order_by(
                        SnapshotMetricValue.metric_key,
                        SnapshotMetricValue.id,
                    )
                )
            )
            if not values:
                writer.writerow(_row(content, snapshot=snapshot))
                continue
            for value in values:
                writer.writerow(_row(content, snapshot=snapshot, value=value))
    return output.getvalue().encode("utf-8-sig")


def _row(
    content: Content,
    *,
    snapshot: DataSnapshot | None = None,
    value: SnapshotMetricValue | None = None,
) -> dict[str, str]:
    raw: dict[str, object | None] = {
        "content_id": content.id,
        "account_id": content.account_id,
        "platform": content.platform.value,
        "content_type": content.content_type.value,
        "platform_content_id": content.platform_content_id,
        "title": (
            content.published_title
            if content.published_title is not None
            else content.title
        ),
        "body": (
            content.published_body
            if content.published_body is not None
            else content.body
        ),
        "status": content.status.value,
        "work_url": content.work_url,
        "published_at": content.published_at,
        "snapshot_id": snapshot.id if snapshot else None,
        "collected_at": snapshot.collected_at if snapshot else None,
        "source": snapshot.source.value if snapshot else None,
        "metric_key": value.metric_key if value else None,
        "raw_value": value.raw_value if value else None,
        "normalized_value": value.normalized_value if value else None,
        "ocr_confidence": value.ocr_confidence if value else None,
    }
    return {field: _string_value(raw[field]) for field in CSV_FIELDS}
