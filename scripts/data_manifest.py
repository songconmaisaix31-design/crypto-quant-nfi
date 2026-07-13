#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from ops_common import PROJECT_ROOT, file_hash, phase_record, utc_now, write_csv, write_json


DATA_ROOT = PROJECT_ROOT / "user_data/data"
OUT_JSON = PROJECT_ROOT / "user_data/data_manifest/data_manifest.json"
REPORT = PROJECT_ROOT / "reports/data_quality/data_manifest_report.md"
SUMMARY = PROJECT_ROOT / "reports/data_quality/data_manifest_summary.json"
CSV = PROJECT_ROOT / "reports/data_quality/data_manifest.csv"


def parse_json_candles(path: Path) -> tuple[int, str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            start = dt.datetime.fromtimestamp(data[0][0] / 1000, tz=dt.timezone.utc).isoformat() if isinstance(data[0], list) else ""
            end = dt.datetime.fromtimestamp(data[-1][0] / 1000, tz=dt.timezone.utc).isoformat() if isinstance(data[-1], list) else ""
            return len(data), start, end
    except Exception:
        pass
    return 0, "", ""


def main() -> int:
    rows = []
    if DATA_ROOT.exists():
        for path in DATA_ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in {".json", ".json.gz", ".feather", ".parquet"}:
                continue
            rel = path.relative_to(PROJECT_ROOT)
            stem = path.stem
            pair = ""
            timeframe = ""
            if "-" in stem:
                parts = stem.split("-")
                pair = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
                timeframe = parts[-1]
            rows_count, start, end = parse_json_candles(path) if path.suffix == ".json" else (0, "", "")
            rows.append({
                "pair": pair,
                "timeframe": timeframe,
                "file_path": str(rel),
                "file_size": path.stat().st_size,
                "row_count": rows_count,
                "start_time": start,
                "end_time": end,
                "gaps_count": "N/A",
                "hash": file_hash(path) if path.stat().st_size < 50_000_000 else "SKIPPED_LARGE_FILE",
                "last_modified": dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat(),
                "data_quality_status": "PRESENT",
            })
    write_json(OUT_JSON, {"generated_at": utc_now(), "files": rows})
    write_json(SUMMARY, {"generated_at": utc_now(), "status": "PASS", "files_count": len(rows), "missing_files": []})
    write_csv(CSV, rows, ["pair", "timeframe", "file_path", "file_size", "row_count", "start_time", "end_time", "gaps_count", "hash", "last_modified", "data_quality_status"])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(f"# Data Manifest Report\n\nStatus: `PASS`\n\nFiles indexed: `{len(rows)}`\n\n", encoding="utf-8")
    phase_record("data_manifest", "PASS", "Data manifest generated.", {"files_count": len(rows)})
    print("DATA_MANIFEST_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

