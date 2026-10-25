PYTHON ?= python
RESOURCE_GROUP ?= rg-careintel-prod-swc
LZ_OUTPUTS ?= ../lz-outputs.txt

.PHONY: install install-synth lint type test budget check synth data pipeline sweep endpoints batch drift api pg-roles lz-env validate-infra preview deploy destroy

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

install-synth:
	$(PYTHON) -m pip install -r requirements-synth.txt

lint:
	ruff check . && ruff format --check .

type:
	mypy

test:
	pytest -q

budget:
	pytest -q tests/test_budget.py

check: lint type test

synth:
	$(PYTHON) -m src.data.synthesize

data:
	$(PYTHON) -m ops.data_asset

pipeline:
	$(PYTHON) -m pipelines.training

sweep:
	$(PYTHON) -m pipelines.training --sweep

endpoints:
	$(PYTHON) -m ops.endpoints --online --batch

batch:
	$(PYTHON) -m pipelines.scoring

drift:
	$(PYTHON) -m src.monitoring.drift --reference data/cohort.parquet --current $(CURRENT) --current-version $(VERSION)

api:
	REQUIRE_AUTH=false uvicorn api.main:app --reload --port 8000

pg-roles:
	$(PYTHON) -m ops.pg_roles --admin $(PG_ADMIN)

lz-env:
	@export MSYS_NO_PATHCONV=1; grep -E '^[a-z][A-Za-z]+=' $(LZ_OUTPUTS) | while IFS='=' read -r key value; do \
	  name=$$(echo "$$key" | sed -E 's/([a-z0-9])([A-Z])/\1_\2/g' | tr '[:lower:]' '[:upper:]'); \
	  azd env set "$$name" "$$(echo "$$value" | tr -d '"')"; \
	done

validate-infra:
	az bicep build --file infra/main.bicep --stdout --only-show-errors > /dev/null && az bicep lint --file infra/main.bicep --only-show-errors

preview:
	az deployment group what-if -g $(RESOURCE_GROUP) -f infra/main.bicep -p infra/main.bicepparam --only-show-errors

deploy:
	azd up --no-prompt

destroy:
	azd down --force --purge
