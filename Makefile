.PHONY: setup test integration up down status terraform
setup:
	uv sync --python 3.11 --extra dev
test:
	uv run pytest -q tests/unit
integration:
	./scripts/test-docker.sh
up:
	docker compose up -d --build broker processor simulator
down:
	docker compose down
status:
	docker compose exec processor python -m iot_ops status --db /data/telemetry.db
terraform:
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform init -backend=false -input=false
	terraform -chdir=infra/terraform validate
