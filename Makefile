SHELL := /bin/bash
.DEFAULT_GOAL := help

# `helm` vem do snap do microk8s; não há binário helm standalone neste host.
HELM ?= microk8s helm3
PYTHON ?= python3
VENV := .venv
VENV_PY := $(VENV)/bin/python

# Alvos que rodam com o cluster desligado. As ondas 0-2 não tocam infra.
.PHONY: help setup ci test lint yaml-shell lint-helm clean

help:
	@echo "datalake-doomsday-env"
	@echo ""
	@echo "  make setup      cria .venv e instala ferramentas de dev"
	@echo "  make ci         validação completa (não requer cluster)"
	@echo "  make test       testes unitários do lakecore"
	@echo "  make lint       shellcheck + helm lint"
	@echo "  make clean      remove artefatos locais"
	@echo ""
	@echo "Estado: Onda 0. Infra, cluster e ingestão ainda não existem."

setup: $(VENV_PY)

$(VENV_PY):
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r requirements-dev.txt
	@echo "venv pronto. Use: $(VENV_PY) -m pytest"

test: setup
	$(VENV_PY) -m pytest -q

lint-helm:
	@if command -v $(HELM) >/dev/null 2>&1; then \
		for chart in charts/*/; do \
			[ -f "$$chart/Chart.yaml" ] || continue; \
			echo "helm lint $$chart"; \
			$(HELM) lint "$$chart" || exit 1; \
		done; \
		echo "helm: nenhum chart para lintar (ok)"; \
	else \
		echo "helm ausente (esperado no Onda 0)"; \
	fi

lint: setup lint-helm lint-sh lint-yaml

lint-sh:
	@scripts=$$(git ls-files '*.sh' 2>/dev/null || find . -name '*.sh' -not -path './.venv/*'); \
	if [ -z "$$scripts" ]; then \
		echo "shellcheck: nenhum script .sh ainda (Onda 3+)"; \
	else \
		echo "shellcheck $$scripts"; \
		$(VENV)/bin/shellcheck $$scripts; \
	fi

lint-yaml:
	@files=$$(git ls-files '*.yml' '*.yaml' 2>/dev/null || find . \( -name '*.yml' -o -name '*.yaml' \) -not -path './.venv/*'); \
	if [ -z "$$files" ]; then \
		echo "yamllint: nenhum YAML ainda"; \
	else \
		echo "yamllint"; \
		$(VENV)/bin/yamllint -c .yamllint $$files; \
	fi

ci: test lint
	@PYTHONPATH=src $(VENV)/bin/python -c "import lakecore; print('lakecore importável:', lakecore.__file__)"
	@echo ""
	@echo "CI concluído com sucesso."

clean:
	rm -rf $(VENV) .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
