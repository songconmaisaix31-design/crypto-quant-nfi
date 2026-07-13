#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
compose logs -f --tail=200 freqtrade

