"""Keep the published REST contract aligned with the running API."""

import json
from pathlib import Path

from app.main import create_app


def test_published_openapi_matches_application() -> None:
    contract = Path(__file__).resolve().parents[2] / "openapi.json"
    published = json.loads(contract.read_text(encoding="utf-8"))
    assert published == create_app().openapi(), (
        "REST contract is stale; regenerate backend/openapi.json using backend/README.md"
    )
