import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / name).read_text())
