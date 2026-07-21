import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.main import app  # noqa: E402


output = ROOT / "packages" / "shared-schemas" / "openapi.json"
output.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
