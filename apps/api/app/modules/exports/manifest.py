import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)


BACKUP_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
BACKUP_PRODUCT_VERSION: Literal["0.1.0"] = "0.1.0"
MAX_BACKUP_BYTES = 2_000_000
MAX_BACKUP_RECORDS = 10_000
MAX_BACKUP_DEPTH = 12
MAX_BACKUP_STRING_LENGTH = 100_000


class BackupFormatError(ValueError):
    pass


class RecordType(StrEnum):
    PLATFORM_ACCOUNT = "platform_account"
    OBJECTIVE_PROFILE = "objective_profile"
    BENCHMARK_PROFILE = "benchmark_profile"
    COLUMN_CAMPAIGN = "column_campaign"
    METRIC_DEFINITION = "metric_definition"
    CONTENT = "content"
    ASSET_REFERENCE = "asset_reference"
    DATA_SNAPSHOT = "data_snapshot"
    SNAPSHOT_METRIC_VALUE = "snapshot_metric_value"
    STYLE_PROFILE = "style_profile"
    STYLE_SAMPLE = "style_sample"
    FACT_SOURCE_METADATA = "fact_source_metadata"
    FACT_ITEM = "fact_item"
    RISK_DOCUMENT_METADATA = "risk_document_metadata"


RECORD_FIELDS: dict[RecordType, tuple[frozenset[str], frozenset[str]]] = {
    RecordType.PLATFORM_ACCOUNT: (
        frozenset({"name"}),
        frozenset({"name"}),
    ),
    RecordType.OBJECTIVE_PROFILE: (
        frozenset(
            {
                "account_id",
                "version",
                "objectives",
                "metric_weights",
                "is_account_default",
            }
        ),
        frozenset(
            {
                "account_id",
                "version",
                "objectives",
                "metric_weights",
                "is_account_default",
            }
        ),
    ),
    RecordType.BENCHMARK_PROFILE: (
        frozenset({"account_id", "version", "sample_size", "is_account_default"}),
        frozenset({"account_id", "version", "sample_size", "is_account_default"}),
    ),
    RecordType.COLUMN_CAMPAIGN: (
        frozenset(
            {
                "account_id",
                "name",
                "kind",
                "starts_at",
                "ends_at",
                "objective_profile_id",
                "benchmark_profile_id",
            }
        ),
        frozenset({"account_id", "name", "kind"}),
    ),
    RecordType.METRIC_DEFINITION: (
        frozenset(
            {
                "content_type",
                "key",
                "label",
                "unit",
                "aggregation",
                "higher_is_better",
                "is_default",
            }
        ),
        frozenset(
            {
                "content_type",
                "key",
                "label",
                "unit",
                "aggregation",
                "higher_is_better",
                "is_default",
            }
        ),
    ),
    RecordType.CONTENT: (
        frozenset(
            {
                "account_id",
                "objective_profile_id",
                "benchmark_profile_id",
                "content_type",
                "column_campaign_id",
                "title",
                "body",
                "work_url",
                "platform_content_id",
                "status",
                "published_title",
                "published_body",
                "published_at",
                "deleted_at",
            }
        ),
        frozenset(
            {
                "account_id",
                "objective_profile_id",
                "benchmark_profile_id",
                "content_type",
                "title",
                "body",
                "status",
            }
        ),
    ),
    RecordType.ASSET_REFERENCE: (
        frozenset({"content_id", "category", "file_name", "mime_type", "size"}),
        frozenset({"content_id", "category", "file_name", "mime_type", "size"}),
    ),
    RecordType.DATA_SNAPSHOT: (
        frozenset(
            {
                "content_id",
                "account_id",
                "content_type",
                "collected_at",
                "age_seconds",
                "maturity_bucket",
                "source",
                "confirmed",
                "confirmed_at",
                "original_screenshot_asset_id",
            }
        ),
        frozenset(
            {
                "content_id",
                "account_id",
                "content_type",
                "collected_at",
                "age_seconds",
                "maturity_bucket",
                "source",
                "confirmed",
            }
        ),
    ),
    RecordType.SNAPSHOT_METRIC_VALUE: (
        frozenset(
            {
                "snapshot_id",
                "metric_key",
                "raw_value",
                "normalized_value",
                "ocr_confidence",
                "eligible_for_benchmark",
                "metric_definition_id",
            }
        ),
        frozenset(
            {
                "snapshot_id",
                "metric_key",
                "eligible_for_benchmark",
            }
        ),
    ),
    RecordType.STYLE_PROFILE: (
        frozenset(
            {
                "account_id",
                "scope_key",
                "version",
                "status",
                "style",
                "sample_content_ids",
                "diff",
                "column_campaign_id",
                "base_profile_id",
                "confirmed_at",
            }
        ),
        frozenset(
            {
                "account_id",
                "scope_key",
                "version",
                "status",
                "style",
                "sample_content_ids",
                "diff",
            }
        ),
    ),
    RecordType.STYLE_SAMPLE: (
        frozenset(
            {
                "account_id",
                "scope_key",
                "content_id",
                "column_campaign_id",
                "selected_at",
            }
        ),
        frozenset({"account_id", "scope_key", "content_id", "selected_at"}),
    ),
    RecordType.FACT_SOURCE_METADATA: (
        frozenset(
            {
                "kind",
                "level",
                "title",
                "status",
                "source_url",
                "file_name",
                "mime_type",
                "size",
                "published_at",
                "accessed_at",
                "untrusted_data",
            }
        ),
        frozenset({"kind", "level", "title", "status", "untrusted_data"}),
    ),
    RecordType.FACT_ITEM: (
        frozenset(
            {
                "source_id",
                "field_name",
                "field_code",
                "value",
                "source_location",
                "confidence",
                "status",
                "conflict_status",
                "confirmed_at",
            }
        ),
        frozenset(
            {
                "source_id",
                "field_name",
                "field_code",
                "value",
                "source_location",
                "confidence",
                "status",
                "conflict_status",
            }
        ),
    ),
    RecordType.RISK_DOCUMENT_METADATA: (
        frozenset(
            {
                "scope",
                "source_level",
                "title",
                "authorization_status",
                "status",
                "version",
                "source_url",
                "private_document_id",
                "published_at",
                "effective_at",
                "accessed_at",
                "previous_version_id",
                "file_name",
                "mime_type",
                "untrusted_data",
                "redistribution_authorized",
            }
        ),
        frozenset(
            {
                "scope",
                "source_level",
                "title",
                "authorization_status",
                "status",
                "version",
                "untrusted_data",
                "redistribution_authorized",
            }
        ),
    ),
}

REFERENCE_FIELDS: dict[
    RecordType, dict[str, tuple[RecordType, bool]]
] = {
    RecordType.OBJECTIVE_PROFILE: {
        "account_id": (RecordType.PLATFORM_ACCOUNT, False)
    },
    RecordType.BENCHMARK_PROFILE: {
        "account_id": (RecordType.PLATFORM_ACCOUNT, False)
    },
    RecordType.COLUMN_CAMPAIGN: {
        "account_id": (RecordType.PLATFORM_ACCOUNT, False),
        "objective_profile_id": (RecordType.OBJECTIVE_PROFILE, True),
        "benchmark_profile_id": (RecordType.BENCHMARK_PROFILE, True),
    },
    RecordType.CONTENT: {
        "account_id": (RecordType.PLATFORM_ACCOUNT, False),
        "objective_profile_id": (RecordType.OBJECTIVE_PROFILE, False),
        "benchmark_profile_id": (RecordType.BENCHMARK_PROFILE, False),
        "column_campaign_id": (RecordType.COLUMN_CAMPAIGN, True),
    },
    RecordType.ASSET_REFERENCE: {
        "content_id": (RecordType.CONTENT, False),
    },
    RecordType.DATA_SNAPSHOT: {
        "content_id": (RecordType.CONTENT, False),
        "account_id": (RecordType.PLATFORM_ACCOUNT, False),
        "original_screenshot_asset_id": (RecordType.ASSET_REFERENCE, True),
    },
    RecordType.SNAPSHOT_METRIC_VALUE: {
        "snapshot_id": (RecordType.DATA_SNAPSHOT, False),
        "metric_definition_id": (RecordType.METRIC_DEFINITION, True),
    },
    RecordType.STYLE_PROFILE: {
        "account_id": (RecordType.PLATFORM_ACCOUNT, False),
        "column_campaign_id": (RecordType.COLUMN_CAMPAIGN, True),
        "base_profile_id": (RecordType.STYLE_PROFILE, True),
    },
    RecordType.STYLE_SAMPLE: {
        "account_id": (RecordType.PLATFORM_ACCOUNT, False),
        "content_id": (RecordType.CONTENT, False),
        "column_campaign_id": (RecordType.COLUMN_CAMPAIGN, True),
    },
    RecordType.FACT_ITEM: {
        "source_id": (RecordType.FACT_SOURCE_METADATA, False),
    },
    RecordType.RISK_DOCUMENT_METADATA: {
        "previous_version_id": (RecordType.RISK_DOCUMENT_METADATA, True),
    },
}

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "claim_token",
    "code_hash",
    "cookie",
    "csrf_hash",
    "encrypted_api_key",
    "lease_expires_at",
    "object_key",
    "password",
    "password_hash",
    "provider_workspace_id",
    "raw_content",
    "session_token",
    "source_text",
    "storage_signing_secret",
    "token",
    "token_hash",
    "vector",
}


def _validate_safe_value(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_BACKUP_DEPTH:
        raise ValueError("backup nesting depth exceeds limit")
    if isinstance(value, str):
        if len(value) > MAX_BACKUP_STRING_LENGTH:
            raise ValueError("backup field length exceeds limit")
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in _SENSITIVE_KEYS or "embedding" in normalized:
                raise ValueError("backup record contains a forbidden field")
            _validate_safe_value(nested, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _validate_safe_value(nested, depth=depth + 1)


class WorkspaceBackup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    name: str = Field(min_length=1, max_length=120)


class StrictRecordData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformAccountData(StrictRecordData):
    name: StrictStr = Field(min_length=1, max_length=120)


class ObjectiveProfileData(StrictRecordData):
    account_id: UUID
    version: StrictInt = Field(gt=0)
    objectives: list[StrictStr] = Field(max_length=100)
    metric_weights: dict[StrictStr, StrictFloat | StrictInt]
    is_account_default: StrictBool


class BenchmarkProfileData(StrictRecordData):
    account_id: UUID
    version: StrictInt = Field(gt=0)
    sample_size: StrictInt = Field(gt=0, le=100_000)
    is_account_default: StrictBool


class ColumnCampaignData(StrictRecordData):
    account_id: UUID
    name: StrictStr = Field(min_length=1, max_length=120)
    kind: Literal["column", "campaign"]
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    objective_profile_id: UUID | None = None
    benchmark_profile_id: UUID | None = None


class MetricDefinitionData(StrictRecordData):
    content_type: Literal["video", "image_text"]
    key: StrictStr = Field(min_length=1, max_length=80)
    label: StrictStr = Field(min_length=1, max_length=120)
    unit: Literal["count", "ratio", "seconds", "number"]
    aggregation: Literal["latest", "sum", "average"]
    higher_is_better: StrictBool
    is_default: StrictBool


class ContentData(StrictRecordData):
    account_id: UUID
    objective_profile_id: UUID
    benchmark_profile_id: UUID
    content_type: Literal["video", "image_text"]
    column_campaign_id: UUID | None = None
    title: StrictStr = Field(max_length=300)
    body: StrictStr = Field(max_length=MAX_BACKUP_STRING_LENGTH)
    work_url: StrictStr | None = Field(default=None, max_length=2048)
    platform_content_id: StrictStr | None = Field(default=None, max_length=255)
    status: Literal["draft", "published", "archived"]
    published_title: StrictStr | None = Field(default=None, max_length=300)
    published_body: StrictStr | None = Field(
        default=None,
        max_length=MAX_BACKUP_STRING_LENGTH,
    )
    published_at: AwareDatetime | None = None
    deleted_at: AwareDatetime | None = None


class AssetReferenceData(StrictRecordData):
    content_id: UUID
    category: Literal["cover", "screenshot", "reference_image", "document"]
    file_name: StrictStr = Field(min_length=1, max_length=255)
    mime_type: StrictStr = Field(min_length=1, max_length=120)
    size: StrictInt = Field(ge=0, le=1_000_000_000)


class DataSnapshotData(StrictRecordData):
    content_id: UUID
    account_id: UUID
    content_type: Literal["video", "image_text"]
    collected_at: AwareDatetime
    age_seconds: StrictInt = Field(ge=0)
    maturity_bucket: StrictStr = Field(min_length=1, max_length=8)
    source: Literal["manual", "tabular_import", "screenshot", "extension"]
    confirmed: StrictBool
    confirmed_at: AwareDatetime | None = None
    original_screenshot_asset_id: UUID | None = None


class SnapshotMetricValueData(StrictRecordData):
    snapshot_id: UUID
    metric_key: StrictStr = Field(min_length=1, max_length=80)
    raw_value: StrictStr | None = Field(default=None, max_length=80)
    normalized_value: StrictStr | None = Field(default=None, max_length=80)
    ocr_confidence: StrictFloat | StrictInt | None = None
    eligible_for_benchmark: StrictBool
    metric_definition_id: UUID | None = None


class StyleProfileData(StrictRecordData):
    account_id: UUID
    scope_key: StrictStr = Field(min_length=1, max_length=80)
    version: StrictInt = Field(gt=0)
    status: Literal["pending_confirmation", "confirmed"]
    style: dict[StrictStr, Any]
    sample_content_ids: list[UUID] = Field(max_length=1_000)
    diff: dict[StrictStr, Any]
    column_campaign_id: UUID | None = None
    base_profile_id: UUID | None = None
    confirmed_at: AwareDatetime | None = None


class StyleSampleData(StrictRecordData):
    account_id: UUID
    scope_key: StrictStr = Field(min_length=1, max_length=80)
    content_id: UUID
    column_campaign_id: UUID | None = None
    selected_at: AwareDatetime


class FactSourceMetadataData(StrictRecordData):
    kind: Literal["document", "image", "link", "text", "web"]
    level: Literal["L1", "L2", "L3", "L4", "L5"]
    title: StrictStr = Field(min_length=1, max_length=300)
    status: Literal["parsed", "awaiting_fetch", "awaiting_model", "failed"]
    source_url: StrictStr | None = Field(default=None, max_length=2048)
    file_name: StrictStr | None = Field(default=None, max_length=255)
    mime_type: StrictStr | None = Field(default=None, max_length=160)
    size: StrictInt | None = Field(default=None, ge=0, le=1_000_000_000)
    published_at: AwareDatetime | None = None
    accessed_at: AwareDatetime | None = None
    untrusted_data: StrictBool


class FactItemData(StrictRecordData):
    source_id: UUID
    field_name: StrictStr = Field(min_length=1, max_length=120)
    field_code: StrictStr = Field(min_length=1, max_length=160)
    value: StrictStr = Field(max_length=MAX_BACKUP_STRING_LENGTH)
    source_location: StrictStr = Field(max_length=500)
    confidence: StrictFloat | StrictInt
    status: Literal["candidate", "confirmed"]
    conflict_status: Literal["clear", "unresolved", "resolved"]
    confirmed_at: AwareDatetime | None = None


class RiskDocumentMetadataData(StrictRecordData):
    scope: Literal["private"]
    source_level: Literal["S1", "S2", "S3", "S4", "S5"]
    title: StrictStr = Field(min_length=1, max_length=300)
    authorization_status: Literal[
        "not_required", "authorized", "unverified", "restricted"
    ]
    status: Literal[
        "draft",
        "parsed",
        "pending_review",
        "active",
        "superseded",
        "expired",
        "rejected",
    ]
    version: StrictInt = Field(gt=0)
    source_url: StrictStr | None = Field(default=None, max_length=2048)
    private_document_id: StrictStr | None = Field(default=None, max_length=255)
    published_at: AwareDatetime | None = None
    effective_at: AwareDatetime | None = None
    accessed_at: AwareDatetime | None = None
    previous_version_id: UUID | None = None
    file_name: StrictStr | None = Field(default=None, max_length=255)
    mime_type: StrictStr | None = Field(default=None, max_length=160)
    untrusted_data: StrictBool
    redistribution_authorized: StrictBool

    @model_validator(mode="after")
    def require_source_reference(self) -> "RiskDocumentMetadataData":
        if self.source_url is None and self.private_document_id is None:
            raise ValueError("risk document metadata requires source reference")
        return self


DATA_MODEL_BY_TYPE: dict[RecordType, type[StrictRecordData]] = {
    RecordType.PLATFORM_ACCOUNT: PlatformAccountData,
    RecordType.OBJECTIVE_PROFILE: ObjectiveProfileData,
    RecordType.BENCHMARK_PROFILE: BenchmarkProfileData,
    RecordType.COLUMN_CAMPAIGN: ColumnCampaignData,
    RecordType.METRIC_DEFINITION: MetricDefinitionData,
    RecordType.CONTENT: ContentData,
    RecordType.ASSET_REFERENCE: AssetReferenceData,
    RecordType.DATA_SNAPSHOT: DataSnapshotData,
    RecordType.SNAPSHOT_METRIC_VALUE: SnapshotMetricValueData,
    RecordType.STYLE_PROFILE: StyleProfileData,
    RecordType.STYLE_SAMPLE: StyleSampleData,
    RecordType.FACT_SOURCE_METADATA: FactSourceMetadataData,
    RecordType.FACT_ITEM: FactItemData,
    RecordType.RISK_DOCUMENT_METADATA: RiskDocumentMetadataData,
}


class PortableRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: RecordType
    source_id: UUID
    platform: Literal["douyin", "xiaohongshu"] | None = None
    data: dict[str, Any]

    @model_validator(mode="after")
    def validate_data_contract(self) -> "PortableRecord":
        allowed, required = RECORD_FIELDS[self.record_type]
        keys = frozenset(self.data)
        if unknown := keys - allowed:
            rendered = ", ".join(sorted(unknown))
            raise ValueError(f"record contains unsupported fields: {rendered}")
        if missing := required - keys:
            rendered = ", ".join(sorted(missing))
            raise ValueError(f"record is missing required fields: {rendered}")
        if self.record_type in {
            RecordType.PLATFORM_ACCOUNT,
            RecordType.METRIC_DEFINITION,
            RecordType.CONTENT,
            RecordType.DATA_SNAPSHOT,
            RecordType.STYLE_PROFILE,
            RecordType.STYLE_SAMPLE,
            RecordType.RISK_DOCUMENT_METADATA,
        } and self.platform is None:
            raise ValueError("platform-scoped record requires platform")
        _validate_safe_value(self.data)
        DATA_MODEL_BY_TYPE[self.record_type].model_validate(self.data)
        return self


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    product_version: Literal["0.1.0"]
    exported_at: AwareDatetime
    workspace: WorkspaceBackup
    records: tuple[PortableRecord, ...] = Field(max_length=MAX_BACKUP_RECORDS)

    @field_validator("exported_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("exported_at must include timezone")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "BackupManifest":
        identities: set[tuple[RecordType, UUID]] = set()
        for record in self.records:
            identity = (record.record_type, record.source_id)
            if identity in identities:
                raise ValueError("duplicate record identity")
            identities.add(identity)
        for record in self.records:
            for field, (target_type, optional) in REFERENCE_FIELDS.get(
                record.record_type, {}
            ).items():
                raw = record.data.get(field)
                if raw is None and optional:
                    continue
                try:
                    target_id = UUID(str(raw))
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"invalid reference in {record.record_type.value}.{field}"
                    ) from error
                if (target_type, target_id) not in identities:
                    raise ValueError(
                        f"broken reference in {record.record_type.value}.{field}"
                    )
            if record.record_type is RecordType.STYLE_PROFILE:
                for raw in record.data["sample_content_ids"]:
                    content_id = UUID(str(raw))
                    if (RecordType.CONTENT, content_id) not in identities:
                        raise ValueError(
                            "broken reference in style_profile.sample_content_ids"
                        )
        return self


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackupFormatError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_manifest_json(raw: bytes) -> BackupManifest:
    if len(raw) > MAX_BACKUP_BYTES:
        raise BackupFormatError("backup size exceeds limit")
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
        _validate_safe_value(payload)
        return BackupManifest.model_validate(payload)
    except BackupFormatError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
        reason = (
            "invalid backup reference"
            if "reference" in str(error).lower()
            else "invalid backup manifest"
        )
        raise BackupFormatError(reason) from error


def canonical_manifest_json(manifest: BackupManifest) -> bytes:
    payload = manifest.model_dump(mode="json")
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
