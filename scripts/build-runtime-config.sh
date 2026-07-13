#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-/mnt/d/AI-Workspace/Projects/crypto-quant-nfi}"
BASE_CONFIG="$PROJECT_ROOT/user_data/config.native.json"
RUNTIME_CONFIG="$PROJECT_ROOT/user_data/config.runtime.json"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ ! -f "$BASE_CONFIG" ]]; then
  echo "[FAIL] Missing $BASE_CONFIG" >&2
  exit 1
fi

python3 - "$BASE_CONFIG" "$RUNTIME_CONFIG" "$ENV_FILE" <<'PY'
import json, secrets, sys
from pathlib import Path
base_path, runtime_path, env_path = map(Path, sys.argv[1:])

def read_env(path: Path) -> dict:
    result = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding='utf-8-sig', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result

env = read_env(env_path)
proxy_url = env.get('FT_PROXY_URL', '')
if not proxy_url:
    print('[FAIL] FT_PROXY_URL is not set in .env', file=sys.stderr)
    sys.exit(1)
if 'PORT' in proxy_url:
    print('[FAIL] FT_PROXY_URL still contains placeholder PORT', file=sys.stderr)
    sys.exit(1)

cfg = json.load(open(base_path, encoding='utf-8'))
errors = []
exchange = cfg.setdefault('exchange', {})
if cfg.get('dry_run') is not True:
    errors.append('dry_run must be true')
if cfg.get('trading_mode') != 'spot':
    errors.append('trading_mode must be spot')
if cfg.get('margin_mode') not in ('', None):
    errors.append('margin_mode must be empty')
if cfg.get('can_short') is True:
    errors.append('can_short must not be true')
for k in ('key', 'secret', 'password'):
    if exchange.get(k):
        errors.append(f'exchange.{k} must be empty')
if exchange.get('name') != 'binance':
    errors.append('exchange.name must be binance')
if errors:
    for err in errors:
        print(f'[FAIL] {err}', file=sys.stderr)
    sys.exit(1)

spot_options = {
    'defaultType': 'spot',
    'fetchMarkets': {'types': ['spot']},
}
proxy_cfg = {
    'enableRateLimit': True,
    'timeout': 60000,
    'httpsProxy': proxy_url,
    'options': spot_options,
}
exchange['key'] = ''
exchange['secret'] = ''
exchange['password'] = ''
exchange['enable_ws'] = False
exchange['ccxt_config'] = proxy_cfg
exchange['ccxt_async_config'] = dict(proxy_cfg)
exchange['pair_whitelist'] = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']
exchange['pair_blacklist'] = [
    '.*(BULL|BEAR|UP|DOWN|3L|3S|5L|5S)/.*',
    '.*(USDC|BUSD|TUSD|FDUSD|DAI|PAX|USD)/USDT',
]
cfg['dry_run'] = True
cfg['trading_mode'] = 'spot'
cfg['margin_mode'] = ''
cfg['can_short'] = False
api = cfg.setdefault('api_server', {})
api['enabled'] = True
api['listen_ip_address'] = '127.0.0.1'
api['listen_port'] = 8080
api['jwt_secret_key'] = env.get('FREQTRADE__API_SERVER__JWT_SECRET_KEY') or secrets.token_urlsafe(48)
api['ws_token'] = env.get('FREQTRADE__API_SERVER__WS_TOKEN') or secrets.token_urlsafe(32)
api['username'] = env.get('FREQTRADE__API_SERVER__USERNAME') or 'freqtrade'
api['password'] = env.get('FREQTRADE__API_SERVER__PASSWORD') or secrets.token_urlsafe(24)
if len(api['jwt_secret_key']) < 32:
    api['jwt_secret_key'] = secrets.token_urlsafe(48)
if len(api['ws_token']) < 25:
    api['ws_token'] = secrets.token_urlsafe(32)
if len(api['password']) < 8:
    api['password'] = secrets.token_urlsafe(24)
json.dump(cfg, open(runtime_path, 'w', encoding='utf-8'), indent=2)
print(f'[PASS] Wrote {runtime_path}')
print('[PASS] Runtime config uses CCXT httpsProxy and Binance spot-only market options')
print('[PASS] Runtime API credentials populated without printing values')
PY