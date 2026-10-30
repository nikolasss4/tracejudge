.PHONY: install ui demo dev serve test lint eval-demo demo-data screenshots

DEMO_DB := .tracejudge/demo.db

install:  ## Python and frontend dependencies
	uv sync
	cd frontend && npm ci

ui:  ## Build the viewer into src/tracejudge/static (served by `tracejudge serve`)
	cd frontend && npm run build

demo: install ui  ## Load the sample runs and open the viewer on http://127.0.0.1:7600
	rm -f $(DEMO_DB)
	uv run tracejudge import demo-data/*.json.gz demo-data/otlp-genai-sample.json --db $(DEMO_DB)
	uv run tracejudge serve --db $(DEMO_DB)

dev:  ## API on :7600 with the demo data, plus the Vite dev server with hot reload on :5173
	uv run tracejudge serve --db $(DEMO_DB) & cd frontend && npm run dev

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	cd frontend && npm run lint

eval-demo:  ## Run the demo regression yourself: v1 vs v2 of the support agent, then diff
	uv run tracejudge eval examples/support_agent/suite.yaml --agent examples.support_agent.agent:run_v1 --label v1
	uv run tracejudge eval examples/support_agent/suite.yaml --agent examples.support_agent.agent:run_v2 --label v2
	uv run tracejudge diff v1 v2

demo-data:  ## Regenerate demo-data/ (simulated model, no API key)
	rm -f .tracejudge/demo-gen.db
	for v in 1 2 3; do \
	  uv run tracejudge eval examples/support_agent/suite.yaml --agent examples.support_agent.agent:run_v$$v \
	    --label v$$v -j 8 --db .tracejudge/demo-gen.db && \
	  uv run tracejudge export v$$v --db .tracejudge/demo-gen.db -o demo-data/support-agent-v$$v.json.gz; \
	done

screenshots:  ## Re-capture docs/img/* from a running `make demo`
	uv run python scripts/screenshots.py
