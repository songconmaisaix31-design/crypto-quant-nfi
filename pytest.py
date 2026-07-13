#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path.cwd()
    tests_dir = root / "tests"
    quiet = "-q" in sys.argv
    failures = []
    count = 0
    for path in sorted(tests_dir.glob("test_*.py")):
        module = load_module(path)
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            count += 1
            try:
                func()
                if not quiet:
                    print(f"PASS {path.name}::{name}")
            except Exception:
                failures.append((path.name, name, traceback.format_exc()))
                print(f"FAIL {path.name}::{name}")
    if failures:
        for file_name, name, tb in failures:
            print(f"\n--- {file_name}::{name} ---\n{tb}")
        print(f"{len(failures)} failed, {count - len(failures)} passed")
        return 1
    print(f"{count} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

