#!/usr/bin/env python3
import argparse
from stable_profit_loop import optimization_experiment

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run-plan-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(optimization_experiment(args.dry_run_plan_only))
