"""One-shot, idempotent object bucket initialization for Compose."""

from app.core.storage import S3Storage


def main() -> int:
    S3Storage().ensure_bucket()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
