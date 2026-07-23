# Cover golden fixtures

These three synthetic images lock the supported primary cover sizes and
deterministic programmatic Chinese typography. They contain no private data.

Regenerate only after visually reviewing an intentional layout change:

```bash
PYTHONPATH=apps/api apps/api/.venv/bin/python \
  apps/api/tests/fixtures/golden-covers/generate.py
```

The test allows a small pixel tolerance for platform CJK font rasterization
differences while separately requiring exact text content and safe-area bounds.
