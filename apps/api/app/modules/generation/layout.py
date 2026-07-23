import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, ConfigDict

from app.modules.generation.cover_models import CoverSize, SafeAreaSpec


class CJKFontUnavailable(RuntimeError):
    pass


class PixelRect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, other: "PixelRect") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )

    def intersects(self, other: "PixelRect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )


class TextPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    lines: tuple[str, ...]
    bounds: PixelRect
    font_size: int
    line_height: int


class CoverLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canvas: PixelRect
    safe_area: PixelRect
    headline: TextPlacement
    subtitle: TextPlacement
    brand: TextPlacement
    logo: PixelRect | None
    font_path: str


@dataclass(frozen=True)
class RenderedCover:
    png_bytes: bytes
    text_content: tuple[str, str, str]
    layout: CoverLayout


_CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)


def resolve_cjk_font_path() -> str:
    configured = os.getenv("COVER_CJK_FONT_PATH")
    candidates = (configured,) if configured else ()
    for candidate in (*candidates, *_CJK_FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise CJKFontUnavailable(
        "a CJK font is required for deterministic cover typography"
    )


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def _line_height(font: ImageFont.FreeTypeFont, spacing: int) -> int:
    box = font.getbbox("国Ag")
    return round(box[3] - box[1] + spacing)


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> tuple[str, ...]:
    if not text:
        return ("",)
    lines: list[str] = []
    current = ""
    for character in text:
        if character == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = f"{current}{character}"
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    lines.append(current)
    return tuple(lines)


def _fit_text(
    *,
    text: str,
    font_path: str,
    max_width: int,
    max_height: int,
    preferred_size: int,
    minimum_size: int,
) -> tuple[tuple[str, ...], int, int, int, int]:
    for font_size in range(preferred_size, minimum_size - 1, -2):
        font = _font(font_path, font_size)
        spacing = max(4, font_size // 7)
        line_height = _line_height(font, spacing)
        lines = _wrap_text(text, font, max_width)
        height = max(1, len(lines) * line_height - spacing)
        width = min(
            max_width,
            max(1, int(max(font.getlength(line) for line in lines))),
        )
        if height <= max_height:
            return lines, font_size, line_height, width, height
    raise ValueError("text cannot fit within the configured safe area")


def _placement(
    *,
    text: str,
    font_path: str,
    x: int,
    y: int,
    max_width: int,
    max_height: int,
    preferred_size: int,
    minimum_size: int,
) -> TextPlacement:
    lines, font_size, line_height, width, height = _fit_text(
        text=text,
        font_path=font_path,
        max_width=max_width,
        max_height=max_height,
        preferred_size=preferred_size,
        minimum_size=minimum_size,
    )
    return TextPlacement(
        text=text,
        lines=lines,
        bounds=PixelRect(x=x, y=y, width=width, height=height),
        font_size=font_size,
        line_height=line_height,
    )


def compute_cover_layout(
    *,
    size: CoverSize,
    headline: str,
    subtitle: str,
    brand_name: str,
    safe_area: SafeAreaSpec | None = None,
    font_path: str | None = None,
    logo_size: tuple[int, int] | None = None,
) -> CoverLayout:
    area = safe_area or SafeAreaSpec()
    resolved_font = font_path or resolve_cjk_font_path()
    safe = PixelRect(
        x=round(size.width * area.x),
        y=round(size.height * area.y),
        width=round(size.width * area.width),
        height=round(size.height * area.height),
    )
    scale = size.width / 1080
    gap = max(16, round(32 * scale))
    brand_height = max(36, round(56 * scale))
    logo: PixelRect | None = None
    brand_width = safe.width
    if logo_size is not None:
        source_width, source_height = logo_size
        if source_width <= 0 or source_height <= 0:
            raise ValueError("logo dimensions must be positive")
        logo_height = brand_height
        logo_width = min(
            round(logo_height * source_width / source_height),
            round(safe.width * 0.3),
        )
        logo = PixelRect(
            x=safe.right - logo_width,
            y=safe.bottom - logo_height,
            width=logo_width,
            height=logo_height,
        )
        brand_width = max(1, logo.x - safe.x - gap)
    brand = _placement(
        text=brand_name,
        font_path=resolved_font,
        x=safe.x,
        y=safe.bottom - brand_height,
        max_width=brand_width,
        max_height=brand_height,
        preferred_size=max(24, round(34 * scale)),
        minimum_size=max(18, round(22 * scale)),
    )
    content_height = brand.bounds.y - safe.y - gap
    headline_placement = _placement(
        text=headline,
        font_path=resolved_font,
        x=safe.x,
        y=safe.y,
        max_width=safe.width,
        max_height=max(1, round(content_height * 0.72)),
        preferred_size=max(48, round(92 * scale)),
        minimum_size=max(24, round(32 * scale)),
    )
    subtitle_y = headline_placement.bounds.bottom + gap
    subtitle_placement = _placement(
        text=subtitle,
        font_path=resolved_font,
        x=safe.x,
        y=subtitle_y,
        max_width=safe.width,
        max_height=max(1, brand.bounds.y - subtitle_y - gap),
        preferred_size=max(28, round(42 * scale)),
        minimum_size=max(18, round(24 * scale)),
    )
    return CoverLayout(
        canvas=PixelRect(x=0, y=0, width=size.width, height=size.height),
        safe_area=safe,
        headline=headline_placement,
        subtitle=subtitle_placement,
        brand=brand,
        logo=logo,
        font_path=resolved_font,
    )


def _draw_text(
    draw: ImageDraw.ImageDraw,
    placement: TextPlacement,
    font_path: str,
    *,
    fill: str,
) -> None:
    font = _font(font_path, placement.font_size)
    y = placement.bounds.y
    for line in placement.lines:
        draw.text((placement.bounds.x, y), line, font=font, fill=fill)
        y += placement.line_height


def render_cover(
    base: Image.Image,
    layout: CoverLayout,
    *,
    logo: Image.Image | None = None,
) -> RenderedCover:
    image = ImageOps.fit(
        base.convert("RGB"),
        (layout.canvas.width, layout.canvas.height),
        method=Image.Resampling.LANCZOS,
    )
    draw = ImageDraw.Draw(image)
    _draw_text(draw, layout.headline, layout.font_path, fill="#ffffff")
    _draw_text(draw, layout.subtitle, layout.font_path, fill="#d7f5ff")
    _draw_text(draw, layout.brand, layout.font_path, fill="#7de7ff")
    if logo is not None:
        if layout.logo is None:
            raise ValueError("layout does not reserve a logo area")
        fitted_logo = ImageOps.fit(
            logo.convert("RGBA"),
            (layout.logo.width, layout.logo.height),
            method=Image.Resampling.LANCZOS,
        )
        image.paste(
            fitted_logo,
            (layout.logo.x, layout.logo.y),
            fitted_logo,
        )
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return RenderedCover(
        png_bytes=output.getvalue(),
        text_content=(
            layout.headline.text,
            layout.subtitle.text,
            layout.brand.text,
        ),
        layout=layout,
    )
