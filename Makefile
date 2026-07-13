SHELL := /bin/bash

.PHONY: setup validate sync-nfi repair-network test-network test-ccxt download-data download-archive import-archive validate-data backtest install-ui start stop restart status logs docker-pull docker-validate docker-start docker-stop

setup:
	./scripts/setup-native.sh

validate:
	./scripts/validate-native.sh

sync-nfi:
	./scripts/sync-nfi.sh

repair-network:
	powershell.exe -ExecutionPolicy Bypass -File scripts/resume-after-wsl-restart.ps1

test-network:
	./scripts/test-network.sh

test-ccxt:
	./scripts/build-runtime-config.sh
	/root/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python scripts/test-ccxt-proxy.py

download-data:
	./scripts/download-data-native.sh

download-archive:
	/root/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python scripts/download-binance-archive.py

import-archive:
	/root/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python scripts/import-binance-archive.py

validate-data:
	/root/.local/share/crypto-quant-nfi/freqtrade/.venv/bin/python scripts/validate-market-data.py

backtest:
	./scripts/backtest-native.sh

install-ui:
	./scripts/install-ui.sh

start:
	./scripts/start-native.sh

stop:
	./scripts/stop-native.sh

restart: stop start

logs:
	./scripts/logs-native.sh

status:
	./scripts/status-native.sh

docker-pull:
	docker pull --platform linux/amd64 freqtradeorg/freqtrade:stable

docker-validate:
	./scripts/validate.sh

docker-start:
	./scripts/start-dry-run.sh

docker-stop:
	./scripts/stop.sh