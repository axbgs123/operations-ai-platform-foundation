from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
from pydantic import ValidationError

from app.modules.generation.cover_models import CoverSize, SafeAreaSpec
from app.modules.generation.layout import (
    compute_cover_layout,
    render_cover,
    resolve_cjk_font_path,
)


GOLDEN_DIR = Path(__file__).parents[1] / "fixtures" / "golden-covers"
REPOSITORY_ROOT = Path(__file__).parents[4]


@pytest.mark.parametrize(
    ("width", "height"),
    [(1080, 1440), (1080, 1920), (1080, 1080)],
)
def test_main_cover_sizes_keep_every_overlay_inside_the_safe_area(
    width: int,
    height: int,
) -> None:
    size = CoverSize(width=width, height=height)

    layout = compute_cover_layout(
        size=size,
        headline="运营内容智能分析",
        subtitle="让每一条内容都有证据",
        brand_name="示例品牌",
    )

    assert layout.canvas.width == width
    assert layout.canvas.height == height
    assert layout.safe_area.contains(layout.headline.bounds)
    assert layout.safe_area.contains(layout.subtitle.bounds)
    assert layout.safe_area.contains(layout.brand.bounds)
    assert not layout.headline.bounds.intersects(layout.subtitle.bounds)
    assert not layout.subtitle.bounds.intersects(layout.brand.bounds)


def test_long_chinese_text_wraps_without_clipping_or_character_loss() -> None:
    headline = "从运营数据到内容生成，每一个结论都能追溯到已确认的事实资料"
    subtitle = "准确排版中文、标点与数字 2026，不让图片模型生成文字。"
    safe_area = SafeAreaSpec(x=0.08, y=0.08, width=0.84, height=0.84)

    layout = compute_cover_layout(
        size=CoverSize(width=1080, height=1440),
        headline=headline,
        subtitle=subtitle,
        brand_name="运营 AI",
        safe_area=safe_area,
    )

    assert "".join(layout.headline.lines) == headline
    assert "".join(layout.subtitle.lines) == subtitle
    assert layout.headline.text == headline
    assert layout.subtitle.text == subtitle
    assert layout.safe_area.contains(layout.headline.bounds)
    assert layout.safe_area.contains(layout.subtitle.bounds)


def test_safe_area_must_stay_within_the_canvas() -> None:
    with pytest.raises(ValidationError):
        SafeAreaSpec(x=0.8, y=0.1, width=0.3, height=0.8)


def test_api_container_installs_a_cjk_font_for_production_rendering() -> None:
    dockerfile = (REPOSITORY_ROOT / "infra/docker/api.Dockerfile").read_text()

    assert "font-noto-cjk" in dockerfile


def test_alpine_noto_font_install_path_is_discoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpine_font = "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc"
    monkeypatch.delenv("COVER_CJK_FONT_PATH", raising=False)
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: str(path) == alpine_font,
    )
    monkeypatch.setattr(Path, "resolve", lambda path: path)

    assert resolve_cjk_font_path() == alpine_font


def test_renderer_keeps_exact_text_metadata_and_png_dimensions() -> None:
    size = CoverSize(width=1080, height=1080)
    layout = compute_cover_layout(
        size=size,
        headline="准确中文：新品 01",
        subtitle="程序叠字，不交给图片模型",
        brand_name="示例品牌",
    )
    base = Image.new("RGB", (size.width, size.height), "#12324a")

    rendered = render_cover(base, layout)

    assert rendered.text_content == (
        "准确中文：新品 01",
        "程序叠字，不交给图片模型",
        "示例品牌",
    )
    decoded = Image.open(BytesIO(rendered.png_bytes))
    assert decoded.size == (1080, 1080)
    assert decoded.mode == "RGB"


@pytest.mark.parametrize(
    ("width", "height"),
    [(1080, 1440), (1080, 1920), (1080, 1080)],
)
def test_template_cover_matches_golden_with_small_pixel_tolerance(
    width: int,
    height: int,
) -> None:
    size = CoverSize(width=width, height=height)
    layout = compute_cover_layout(
        size=size,
        headline="运营内容智能分析",
        subtitle="准确中文 · 证据驱动",
        brand_name="Operations AI",
    )
    base = Image.new("RGB", (width, height), "#102a43")
    rendered = render_cover(base, layout)
    actual = Image.open(BytesIO(rendered.png_bytes)).convert("RGB")
    expected = Image.open(GOLDEN_DIR / f"template-{width}x{height}.png").convert("RGB")

    difference = ImageChops.difference(actual, expected)
    mean_difference = sum(ImageStat.Stat(difference).mean) / 3
    changed = difference.convert("L").point(lambda value: 255 if value > 12 else 0)
    changed_ratio = changed.histogram()[255] / (width * height)

    assert mean_difference <= 4
    assert changed_ratio <= 0.04
