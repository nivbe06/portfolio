# Absolute paths, so dbt and DuckDB resolve the same files whatever the caller's
# working directory is. Relative paths in a DuckDB view break the moment someone
# opens the warehouse from elsewhere.
ROOT := $(shell pwd)
export TALON_RAW_ROOT     := $(ROOT)/data/raw
export TALON_SERVING_ROOT := $(ROOT)/data/serving

# --profiles-dir must follow the subcommand in dbt 1.11, not precede it.
DBT_FLAGS := --profiles-dir .
TENANT  ?= acme-commerce
QUARTER ?= 2026-Q2

.PHONY: all generate build serve stop payloads render test clean check

all: generate build serve

## Write ~2.18M mock events to data/raw. --scale 0.05 for a quick run.
generate:
	python3 generate/gen_logs.py
	python3 generate/dump_seeds.py

## Run the DAG and every test, then refresh the semantic layer if it is running.
##
## dbt never blocks on Cube: they touch different files, which is the whole
## point of publishing rpt_ as parquet. But rewriting the parquet underneath a
## running Cube leaves it holding stale handles, so it needs a restart once the
## publish is done. That is a refresh, not a lock, and it never fails the build.
build:
	@mkdir -p data/serving   # dbt writes the rpt_ files here but will not create the directory
	cd dbt && dbt build $(DBT_FLAGS)
	@if docker compose -f cube/docker-compose.yml ps --status running 2>/dev/null | grep -q cube; then \
		echo "--> refreshing serving layer"; \
		docker compose -f cube/docker-compose.yml restart >/dev/null 2>&1; \
		for i in 1 2 3 4 5 6 7 8 9 10 11 12; do \
			code=$$(curl -s -o /dev/null -w "%{http_code}" http://localhost:4000/cubejs-api/v1/meta 2>/dev/null); \
			[ "$$code" = "200" ] && { echo "--> serving layer ready"; break; }; \
			sleep 5; \
		done; \
	fi

## Start the semantic layer on http://localhost:4000
serve:
	docker compose -f cube/docker-compose.yml up -d

stop:
	docker compose -f cube/docker-compose.yml down

## Phase 1 only: query the semantic layer and rank anomalies, then stop.
## Writes qbr/created-qbrs/payloads-<tenant>-<quarter>.json for a writer to work from.
##
## There is no `make qbr`. A QBR needs prose, and the thing that writes the
## prose is the agent running /create-qbr, not this Makefile. Run that instead:
## it does both phases and writes the narrative in between, with no API key.
payloads:
	python3 qbr/build_qbr.py --tenant $(TENANT) --quarter $(QUARTER) --emit-payloads \
		$(if $(FOCUS),--focus "$(FOCUS)",)

## Phase 2: check the prose against source and render. NARRATIVES=<path> required.
render:
	python3 qbr/build_qbr.py --tenant $(TENANT) --quarter $(QUARTER) --json \
		--with-narratives $(NARRATIVES)

## Python-side tests. The dbt tests run as part of `make build`.
test:
	python3 qbr/test_grounding.py
	python3 qbr/test_retrieval.py

## The two access-control checks, run against a live Cube.
check:
	python3 qbr/test_boundary.py

clean:
	rm -rf data/raw data/serving data/warehouse.duckdb dbt/target
