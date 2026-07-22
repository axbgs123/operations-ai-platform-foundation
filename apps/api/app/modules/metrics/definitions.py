from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.modules.content.account_models import Platform
from app.modules.metrics.models import (
    ContentType,
    MetricAggregation,
    MetricDefinition,
    MetricUnit,
)


@dataclass(frozen=True, slots=True)
class MetricDefinitionSpec:
    platform: Platform
    content_type: ContentType
    key: str
    label: str
    unit: MetricUnit
    aggregation: MetricAggregation
    higher_is_better: bool


def _metric(
    platform: Platform,
    content_type: ContentType,
    key: str,
    label: str,
    unit: MetricUnit = MetricUnit.COUNT,
    *,
    higher_is_better: bool = True,
) -> MetricDefinitionSpec:
    return MetricDefinitionSpec(
        platform=platform,
        content_type=content_type,
        key=key,
        label=label,
        unit=unit,
        aggregation=MetricAggregation.LATEST,
        higher_is_better=higher_is_better,
    )


def _common_engagement_metrics(
    platform: Platform,
    content_type: ContentType,
) -> tuple[MetricDefinitionSpec, ...]:
    sharing_metrics = (
        (
            _metric(platform, content_type, "shares", "分享"),
            _metric(platform, content_type, "favorites", "收藏"),
        )
        if platform == Platform.DOUYIN
        else (
            _metric(platform, content_type, "favorites", "收藏"),
            _metric(platform, content_type, "shares", "分享"),
        )
    )
    return (
        _metric(platform, content_type, "likes", "点赞"),
        _metric(platform, content_type, "comments", "评论"),
        *sharing_metrics,
    )


def _growth_metrics(
    platform: Platform,
    content_type: ContentType,
) -> tuple[MetricDefinitionSpec, ...]:
    return (
        _metric(platform, content_type, "profile_visits", "主页访问"),
        _metric(platform, content_type, "followers_gained", "新增关注"),
    )


def _douyin_metrics(content_type: ContentType) -> tuple[MetricDefinitionSpec, ...]:
    platform = Platform.DOUYIN
    common = (
        _metric(platform, content_type, "views", "播放量"),
        *_common_engagement_metrics(platform, content_type),
    )
    if content_type == ContentType.IMAGE_TEXT:
        return (*common, *_growth_metrics(platform, content_type))
    return (
        *common,
        _metric(
            platform,
            content_type,
            "bounce_rate_2s",
            "2 秒跳出率",
            MetricUnit.RATIO,
            higher_is_better=False,
        ),
        _metric(
            platform,
            content_type,
            "completion_rate_5s",
            "5 秒完播率",
            MetricUnit.RATIO,
        ),
        _metric(
            platform,
            content_type,
            "completion_rate",
            "整体完播率",
            MetricUnit.RATIO,
        ),
        _metric(
            platform,
            content_type,
            "average_watch_duration",
            "平均播放时长",
            MetricUnit.SECONDS,
        ),
        *_growth_metrics(platform, content_type),
    )


def _xiaohongshu_metrics(content_type: ContentType) -> tuple[MetricDefinitionSpec, ...]:
    platform = Platform.XIAOHONGSHU
    common = (
        _metric(platform, content_type, "impressions", "曝光量"),
        _metric(platform, content_type, "views", "阅读/播放量"),
        _metric(
            platform,
            content_type,
            "cover_click_rate",
            "封面点击率",
            MetricUnit.RATIO,
        ),
        *_common_engagement_metrics(platform, content_type),
        *_growth_metrics(platform, content_type),
    )
    if content_type == ContentType.IMAGE_TEXT:
        return common
    return (
        *common,
        _metric(
            platform,
            content_type,
            "average_watch_duration",
            "平均观看时长",
            MetricUnit.SECONDS,
        ),
        _metric(
            platform,
            content_type,
            "completion_rate",
            "完播率",
            MetricUnit.RATIO,
        ),
    )


DEFAULT_METRIC_REGISTRY: dict[
    tuple[Platform, ContentType], tuple[MetricDefinitionSpec, ...]
] = {
    (platform, content_type): (
        _douyin_metrics(content_type)
        if platform == Platform.DOUYIN
        else _xiaohongshu_metrics(content_type)
    )
    for platform in Platform
    for content_type in ContentType
}


def get_metric_definitions(
    platform: Platform,
    content_type: ContentType,
) -> tuple[MetricDefinitionSpec, ...]:
    return DEFAULT_METRIC_REGISTRY[(platform, content_type)]


def validate_metric_values(
    platform: Platform,
    content_type: ContentType,
    values: Mapping[str, Decimal | float | int | None],
    *,
    custom_definitions: Iterable[MetricDefinition] = (),
) -> dict[str, Decimal | None]:
    compatible_keys = {
        definition.key for definition in get_metric_definitions(platform, content_type)
    }
    compatible_keys.update(
        definition.key
        for definition in custom_definitions
        if definition.platform == platform and definition.content_type == content_type
    )

    incompatible = set(values) - compatible_keys
    if incompatible:
        keys = ", ".join(sorted(incompatible))
        raise ValueError(
            f"metric(s) {keys} not compatible with {platform.value}/{content_type.value}"
        )

    return {
        key: None if value is None else Decimal(str(value))
        for key, value in values.items()
    }


def derive_metrics(
    platform: Platform,
    content_type: ContentType,
    values: Mapping[str, Decimal | float | int | None],
) -> dict[str, Decimal]:
    validated = validate_metric_values(platform, content_type, values)
    derived: dict[str, Decimal] = {}

    views = validated.get("views")
    engagement_keys = ("likes", "comments", "shares", "favorites")
    engagement_values: list[Decimal] = []
    for key in engagement_keys:
        value = validated.get(key)
        if value is not None:
            engagement_values.append(value)
    if views is not None and views > 0 and engagement_values:
        derived["engagement_rate"] = sum(
            engagement_values,
            start=Decimal(0),
        ) / views

    profile_visits = validated.get("profile_visits")
    if views is not None and views > 0 and profile_visits is not None:
        derived["profile_visit_rate"] = profile_visits / views

    followers_gained = validated.get("followers_gained")
    if (
        profile_visits is not None
        and profile_visits > 0
        and followers_gained is not None
    ):
        derived["follow_conversion_rate"] = followers_gained / profile_visits

    return derived
