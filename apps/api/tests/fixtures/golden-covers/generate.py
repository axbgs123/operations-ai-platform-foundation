"""Regenerate deterministic cover golden images after intentional review."""

from pathlib import Path

from PIL import Image

from app.modules.generation.cover_models import CoverSize
from app.modules.generation.layout import compute_cover_layout, render_cover


OUTPUT_DIR = Path(__file__).parent
SIZES = ((1080, 1440), (1080, 1920), (1080, 1080))


def main() -> None:
    for width, height in SIZES:
        size = CoverSize(width=width, height=height)
        layout = compute_cover_layout(
            size=size,
            headline="运营内容智能分析",
            subtitle="准确中文 · 证据驱动",
            brand_name="Operations AI",
        )
        rendered = render_cover(
            Image.new("RGB", (width, height), "#102a43"),
            layout,
        )
        output = OUTPUT_DIR / f"template-{width}x{height}.png"
        output.write_bytes(rendered.png_bytes)
        print(output)


if __name__ == "__main__":
    main()
