#!/usr/bin/env python3
import argparse
from stable_profit_loop import walkforward

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(walkforward(args.plan_only))
