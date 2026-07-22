from decimal import Decimal

import pytest

from app.modules.content.account_models import Platform
from app.modules.metrics.definitions import derive_metrics
from app.modules.metrics.models import ContentType


def test_derived_rates_are_calculated_from_compatible_douyin_metrics() -> None:
    derived = derive_metrics(
        Platform.DOUYIN,
        ContentType.VIDEO,
        {
            "views": 100,
            "likes": 10,
            "comments": 2,
            "shares": 3,
            "favorites": 5,
            "profile_visits": 8,
            "followers_gained": 2,
        },
    )

    assert derived == {
        "engagement_rate": Decimal("0.2"),
        "profile_visit_rate": Decimal("0.08"),
        "follow_conversion_rate": Decimal("0.25"),
    }


@pytest.mark.parametrize("denominator", [None, 0, -1])
def test_view_based_rates_are_omitted_when_views_are_not_valid(
    denominator: int | None,
) -> None:
    derived = derive_metrics(
        Platform.XIAOHONGSHU,
        ContentType.IMAGE_TEXT,
        {"views": denominator, "likes": 4, "profile_visits": 2},
    )

    assert "engagement_rate" not in derived
    assert "profile_visit_rate" not in derived


@pytest.mark.parametrize("denominator", [None, 0, -1])
def test_follow_conversion_is_omitted_when_profile_visits_are_not_valid(
    denominator: int | None,
) -> None:
    derived = derive_metrics(
        Platform.DOUYIN,
        ContentType.VIDEO,
        {"views": 100, "profile_visits": denominator, "followers_gained": 2},
    )

    assert "follow_conversion_rate" not in derived


def test_derived_metrics_reject_cross_platform_input_before_calculation() -> None:
    with pytest.raises(ValueError, match="not compatible"):
        derive_metrics(
            Platform.DOUYIN,
            ContentType.VIDEO,
            {"impressions": 100, "views": 50},
        )
