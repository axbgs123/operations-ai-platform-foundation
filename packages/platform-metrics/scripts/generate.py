from pathlib import Path

from app.modules.metrics.typescript import render_typescript_registry


OUTPUT = Path(__file__).parents[1] / "src" / "index.ts"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_typescript_registry())


if __name__ == "__main__":
    main()
