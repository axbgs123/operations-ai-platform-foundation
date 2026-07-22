from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError

from app.modules.content.account_models import Platform
from app.modules.metrics.definitions import (
    get_metric_definitions,
    validate_metric_values,
)
from app.modules.metrics.models import (
    ContentType,
    MetricAggregation,
    MetricDefinition,
    MetricUnit,
)
from app.modules.metrics.schemas import MetricDefinitionCreate, MetricValuesInput
from app.modules.metrics.typescript import render_typescript_registry


EXPECTED_DEFAULT_KEYS = {
    (Platform.DOUYIN, ContentType.VIDEO): (
        "views",
        "likes",
        "comments",
        "shares",
        "favorites",
        "bounce_rate_2s",
        "completion_rate_5s",
        "completion_rate",
        "average_watch_duration",
        "profile_visits",
        "followers_gained",
    ),
    (Platform.DOUYIN, ContentType.IMAGE_TEXT): (
        "views",
        "likes",
        "comments",
        "shares",
        "favorites",
        "profile_visits",
        "followers_gained",
    ),
    (Platform.XIAOHONGSHU, ContentType.VIDEO): (
        "impressions",
        "views",
        "cover_click_rate",
        "likes",
        "comments",
        "favorites",
        "shares",
        "profile_visits",
        "followers_gained",
        "average_watch_duration",
        "completion_rate",
    ),
    (Platform.XIAOHONGSHU, ContentType.IMAGE_TEXT): (
        "impressions",
        "views",
        "cover_click_rate",
        "likes",
        "comments",
        "favorites",
        "shares",
        "profile_visits",
        "followers_gained",
    ),
}

ROOT = Path(__file__).parents[4]


@pytest.mark.parametrize(
    ("platform", "content_type", "expected_keys"),
    [
        (platform, content_type, expected_keys)
        for (platform, content_type), expected_keys in EXPECTED_DEFAULT_KEYS.items()
    ],
)
def test_default_metric_registry_is_isolated_by_platform_and_content_type(
    platform: Platform,
    content_type: ContentType,
    expected_keys: tuple[str, ...],
) -> None:
    definitions = get_metric_definitions(platform, content_type)

    assert tuple(definition.key for definition in definitions) == expected_keys
    assert all(definition.platform == platform for definition in definitions)
    assert all(definition.content_type == content_type for definition in definitions)


@pytest.mark.parametrize(
    ("platform", "content_type", "invalid_key"),
    [
        (Platform.DOUYIN, ContentType.VIDEO, "impressions"),
        (Platform.XIAOHONGSHU, ContentType.IMAGE_TEXT, "average_watch_duration"),
        (Platform.DOUYIN, ContentType.IMAGE_TEXT, "completion_rate"),
    ],
)
def test_incompatible_platform_or_content_type_metric_is_rejected(
    platform: Platform,
    content_type: ContentType,
    invalid_key: str,
) -> None:
    with pytest.raises(ValueError, match="not compatible"):
        validate_metric_values(platform, content_type, {invalid_key: 1})


def test_known_metric_allows_null_without_guessing_a_value() -> None:
    validated = validate_metric_values(
        Platform.DOUYIN,
        ContentType.VIDEO,
        {"views": None, "likes": 12},
    )

    assert validated == {"views": None, "likes": 12.0}


def test_matching_workspace_custom_metric_is_accepted_but_cross_platform_use_is_rejected() -> None:
    custom = MetricDefinition(
        workspace_id=uuid4(),
        platform=Platform.DOUYIN,
        content_type=ContentType.VIDEO,
        key="qualified_leads",
        label="有效线索",
        unit=MetricUnit.COUNT,
        aggregation=MetricAggregation.LATEST,
        higher_is_better=True,
        is_default=False,
    )

    assert validate_metric_values(
        Platform.DOUYIN,
        ContentType.VIDEO,
        {"qualified_leads": 3},
        custom_definitions=[custom],
    ) == {"qualified_leads": 3.0}

    with pytest.raises(ValueError, match="not compatible"):
        validate_metric_values(
            Platform.XIAOHONGSHU,
            ContentType.VIDEO,
            {"qualified_leads": 3},
            custom_definitions=[custom],
        )


def test_metric_definition_exposes_required_registry_fields() -> None:
    assert {
        "platform",
        "content_type",
        "key",
        "unit",
        "aggregation",
        "higher_is_better",
    } <= set(MetricDefinition.__table__.columns.keys())


def test_typescript_registry_contains_display_metadata_but_no_derived_formulas() -> None:
    source = render_typescript_registry()

    assert "export const PLATFORM_METRICS" in source
    assert '"douyin:video"' in source
    assert '"xiaohongshu:image_text"' in source
    assert 'label: "2 秒跳出率"' in source
    assert "engagement_rate" not in source
    assert "follow_conversion_rate" not in source


def test_metric_schemas_preserve_nulls_and_reject_noncanonical_custom_keys() -> None:
    values = MetricValuesInput(values={"views": None, "likes": 2})

    assert values.values == {"views": None, "likes": 2.0}
    with pytest.raises(ValidationError):
        MetricDefinitionCreate(
            workspace_id=uuid4(),
            platform="douyin",
            content_type="video",
            key="Qualified Leads",
            label="有效线索",
            unit="count",
        )


def test_migration_chain_creates_metric_definitions_table() -> None:
    config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
    output = StringIO()

    with redirect_stdout(output):
        command.upgrade(config, "head", sql=True)

    assert "CREATE TABLE metric_definitions" in output.getvalue()
