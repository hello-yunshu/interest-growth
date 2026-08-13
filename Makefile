.PHONY: test run audit init-db web docker-up docker-down

init-db:
	PYTHONPATH=apps/api:packages/domain:packages/plugin-runtime:packages/engine-contracts:packages/event-bus:packages/artifacts:packages/shared:packages/native-execution-core:adapters/deepseek python -m pg_api.cli init-db

run:
	PYTHONPATH=apps/api:packages/domain:packages/plugin-runtime:packages/engine-contracts:packages/event-bus:packages/artifacts:packages/shared:packages/native-execution-core:adapters/deepseek uvicorn pg_api.main:app --reload --host 127.0.0.1 --port 8000

test:
	pytest

audit:
	python scripts/self_audit.py

web:
	cd apps/web && npm run dev

docker-up:
	docker compose up --build

docker-down:
	docker compose down


.PHONY: desktop-sidecar desktop-web desktop-check
desktop-sidecar:
	python scripts/build_desktop_sidecar.py

desktop-web:
	npm --prefix apps/web run build

desktop-check:
	python -m pytest && python scripts/self_audit.py
