#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

from ops_common import PROJECT_ROOT, phase_record, redact_text, utc_now, write_csv, write_json


OUT = PROJECT_ROOT / "reports/audit"
SUMMARY = OUT / "audit_summary.json"
REPORT = OUT / "audit_report.md"
LOGS = OUT / "audit_logs.txt"
SCAN_ROOTS = ["scripts", "configs", "reports", "user_data", "docs"]
EXCLUDE_PARTS = {"venv", ".venv", "node_modules", "__pycache__", "data", "archive_cache", "backtest_results"}
EXCLUDE_SUFFIXES = {".zip", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".feather", ".parquet", ".pyc"}
PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token|signature|private[_-]?key)\s*[:=]\s*['\"]([A-Za-z0-9_./+=:-]{16,})['\"]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{8,}\b"),
]
SAFE_REFERENCE_TERMS = ("os.environ", "getenv", "[REDACTED]", "example", "template", "placeholder", "BINANCE_TESTNET_KEY", "BINANCE_TESTNET_SECRET")


def should_scan(path: Path) -> bool:
    rel = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDE_PARTS for part in rel.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    if path.stat().st_size > 2_000_000:
        return False
    return path.is_file()


def main() -> int:
    findings = []
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not should_scan(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for pattern in PATTERNS:
                    if pattern.search(line):
                        if any(term in line for term in SAFE_REFERENCE_TERMS):
                            continue
                        findings.append({
                            "file": str(path.relative_to(PROJECT_ROOT)),
                            "line": line_no,
                            "pattern": pattern.pattern[:80],
                            "sample": redact_text(line.strip())[:200],
                        })
                        break
    status = "PASS" if not findings else "REVIEW"
    rows = [{"file": f["file"], "line": f["line"], "pattern": f["pattern"], "sample": f["sample"]} for f in findings]
    write_csv(OUT / "secret_scan_findings.csv", rows, ["file", "line", "pattern", "sample"])
    summary = {"generated_at": utc_now(), "status": status, "findings_count": len(findings), "findings": findings[:200]}
    write_json(SUMMARY, summary)
    lines = [
        "# Secret Scan Report",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"Status: `{status}`",
        f"Findings: `{len(findings)}`",
        "",
        "Findings are redacted and require review. Full secret-like values are not printed.",
    ]
    if findings:
        lines += ["", "| file | line | sample |", "|---|---:|---|"]
        for f in findings[:100]:
            lines.append(f"| `{f['file']}` | {f['line']} | `{f['sample']}` |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGS.write_text("\n".join(f"{f['file']}:{f['line']} {f['sample']}" for f in findings) + "\n", encoding="utf-8")
    phase_record("secret_scan", "PASS" if status == "PASS" else "REVIEW", f"Secret scan completed with {len(findings)} findings.", {"findings_count": len(findings)})
    print(f"SECRET_SCAN_STATUS={status}")
    print(f"SECRET_SCAN_FINDINGS={len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
