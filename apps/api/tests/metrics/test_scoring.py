from decimal import Decimal

import pytest

from app.modules.metrics.scoring import SCORE_DISCLAIMER, composite_score


def test_composite_score_is_disabled_by_default() -> None:
    result = composite_score(
        {"views": Decimal("0.9")},
        {"views": Decimal("1")},
    )

    assert result.enabled is False
    assert result.value is None
    assert result.disclaimer is None


def test_enabled_score_renormalizes_weights_for_missing_metrics() -> None:
    result = composite_score(
        {"views": Decimal("0.8"), "likes": None},
        {"views": Decimal("1"), "likes": Decimal("3")},
        enabled=True,
    )

    assert result.enabled is True
    assert result.value == Decimal("80.0")
    assert result.effective_weights == {"views": Decimal("1")}
    assert result.disclaimer == SCORE_DISCLAIMER
    assert result.disclaimer == "非平台官方评分或客观内容质量分"


def test_enabled_score_is_an_account_history_percentile_score() -> None:
    result = composite_score(
        {"views": Decimal("0.9"), "engagement": Decimal("0.4")},
        {"views": Decimal("3"), "engagement": Decimal("1")},
        enabled=True,
    )

    assert result.value == Decimal("77.5")
    assert result.effective_weights == {
        "views": Decimal("0.75"),
        "engagement": Decimal("0.25"),
    }


def test_score_rejects_non_percentile_inputs() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        composite_score(
            {"views": Decimal("90")},
            {"views": Decimal("1")},
            enabled=True,
        )
