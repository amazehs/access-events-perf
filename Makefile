PY ?= python3
VARIANT ?= baseline

.PHONY: help install test serve seed smoke quick suite suite-all compare explain clean

help:
	@echo "make install            create .venv and install dependencies"
	@echo "make test               run functional tests (pytest)"
	@echo "make serve VARIANT=...  seed and run the API on :8000 (docs at /docs)"
	@echo "make smoke              30 s threshold-gated load test (optimized)"
	@echo "make quick VARIANT=...  short version of every scenario (~6 min)"
	@echo "make suite VARIANT=...  full suite for one variant (~45 min)"
	@echo "make suite-all          full suite for all three variants, twice each (~4.5 h)"
	@echo "make compare            charts and comparison table from results/"
	@echo "make explain            SQLite query plans for baseline and optimized"

install:
	$(PY) -m venv .venv
	.venv/bin/pip install -r requirements.txt
	@echo "Now run: source .venv/bin/activate"

test:
	$(PY) -m pytest -q

seed:
	$(PY) -m app.seed --variant $(VARIANT) --db data/$(VARIANT).db

serve: seed
	APP_VARIANT=$(VARIANT) DB_PATH=data/$(VARIANT).db $(PY) -m uvicorn app.main:app --port 8000

smoke:
	$(PY) scripts/run_suite.py --variant optimized --profile smoke --clean --strict

quick:
	$(PY) scripts/run_suite.py --variant $(VARIANT) --profile quick --clean

suite:
	$(PY) scripts/run_suite.py --variant $(VARIANT) --profile full --clean

suite-all:
	for v in baseline paginated optimized; do $(PY) scripts/run_suite.py --variant $$v --profile full --repeat 2 --clean; done
	$(MAKE) compare

compare:
	$(PY) scripts/compare.py $(wildcard results/baseline) $(wildcard results/paginated) $(wildcard results/optimized)

explain:
	$(PY) -m app.seed --variant baseline --db data/baseline.db
	$(PY) -m app.seed --variant optimized --db data/optimized.db
	$(PY) scripts/explain_queries.py data/baseline.db
	$(PY) scripts/explain_queries.py data/optimized.db

clean:
	rm -rf data/*.db* .pytest_cache __pycache__ */__pycache__
