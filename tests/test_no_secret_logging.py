import gzip
import json
import tempfile
from pathlib import Path

from market_intelligence.raw_store import append_raw


def test_raw_store_redacts_secret_fields():
    with tempfile.TemporaryDirectory() as directory:
        result = {"source_id": "test", "provider": "test", "status": "AVAILABLE", "request_id": "abc", "payload": {"api_key": "never-store-this", "value": 1}}
        manifest = append_raw(Path(directory), result)
        with gzip.open(manifest["path"], "rt", encoding="utf-8") as handle:
            text = handle.read()
        assert "never-store-this" not in text
        assert "[REDACTED]" in text
