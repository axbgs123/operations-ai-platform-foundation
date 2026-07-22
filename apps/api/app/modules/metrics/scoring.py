from dataclasses import dataclass
from decimal import Decimal


SCORE_DISCLAIMER = "非平台官方评分或客观内容质量分"


@dataclass(frozen=True)
class CompositeScore:
    enabled: bool
    value: Decimal | None
    effective_weights: dict[str, Decimal]
    disclaimer: str | None


def composite_score(
    account_historical_percentiles: dict[str, Decimal | None],
    weights: dict[str, Decimal],
    *,
    enabled: bool = False,
) -> CompositeScore:
    if not enabled:
        return CompositeScore(
            enabled=False,
            value=None,
            effective_weights={},
            disclaimer=None,
        )

    available: dict[str, tuple[Decimal, Decimal]] = {}
    for metric_key, percentile_value in account_historical_percentiles.items():
        if percentile_value is None or metric_key not in weights:
            continue
        if not Decimal(0) <= percentile_value <= Decimal(1):
            raise ValueError("historical percentile must be between 0 and 1")
        weight = weights[metric_key]
        if weight < 0:
            raise ValueError("metric weights must not be negative")
        if weight > 0:
            available[metric_key] = (percentile_value, weight)

    total_weight = sum((weight for _, weight in available.values()), Decimal(0))
    if total_weight == 0:
        return CompositeScore(
            enabled=True,
            value=None,
            effective_weights={},
            disclaimer=SCORE_DISCLAIMER,
        )
    effective_weights = {
        key: weight / total_weight for key, (_, weight) in available.items()
    }
    score = sum(
        (
            percentile_value * effective_weights[key] * Decimal(100)
            for key, (percentile_value, _) in available.items()
        ),
        Decimal(0),
    )
    return CompositeScore(
        enabled=True,
        value=score,
        effective_weights=effective_weights,
        disclaimer=SCORE_DISCLAIMER,
    )
