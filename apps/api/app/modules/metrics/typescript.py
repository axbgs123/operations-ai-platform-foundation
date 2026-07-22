import json

from app.modules.metrics.definitions import DEFAULT_METRIC_REGISTRY


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_typescript_registry() -> str:
    lines = [
        "// Generated from the API metric registry. Do not edit manually.",
        'export type Platform = "douyin" | "xiaohongshu";',
        'export type ContentType = "video" | "image_text";',
        'export type MetricUnit = "count" | "ratio" | "seconds" | "number";',
        'export type MetricAggregation = "latest" | "sum" | "average";',
        "",
        "export interface MetricDisplayMetadata {",
        "  key: string;",
        "  label: string;",
        "  unit: MetricUnit;",
        "  aggregation: MetricAggregation;",
        "  higherIsBetter: boolean;",
        "}",
        "",
        "export const PLATFORM_METRICS = {",
    ]
    for (platform, content_type), definitions in DEFAULT_METRIC_REGISTRY.items():
        lines.append(f'  "{platform.value}:{content_type.value}": [')
        for definition in definitions:
            lines.extend(
                [
                    "    {",
                    f"      key: {_quote(definition.key)},",
                    f"      label: {_quote(definition.label)},",
                    f"      unit: {_quote(definition.unit.value)},",
                    f"      aggregation: {_quote(definition.aggregation.value)},",
                    "      higherIsBetter: "
                    f"{str(definition.higher_is_better).lower()},",
                    "    },",
                ]
            )
        lines.append("  ],")
    lines.extend(
        [
            "} as const satisfies Record<",
            "  `${Platform}:${ContentType}`,",
            "  readonly MetricDisplayMetadata[]",
            ">;",
            "",
        ]
    )
    return "\n".join(lines)
