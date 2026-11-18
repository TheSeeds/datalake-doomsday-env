SHELL := /bin/bash
.DEFAULT_GOAL := help

# `helm` vem do snap do microk8s; não há binário helm standalone neste host.
HELM ?= microk8s helm3
PYTHON ?= python3
VENV := .venv
VENV_PY := $(VENV)/bin/python

# Alvos que rodam com o cluster desligado. As ondas 0-2 não tocam infra.
.PHONY: help setup ci ci-check test lint lint-sh lint-yaml lint-helm ingest-demo clean

help:
	@echo "datalake-doomsday-env"
	@echo ""
	@echo "  make setup      cria .venv e instala ferramentas de dev"
	@echo "  make ci         validação completa (não requer cluster)"
	@echo "  make ci-check   igual a ci, mas falha o shell se algo falhar (use em push/CI)"
	@echo "  make test       testes unitários do lakecore"
	@echo "  make ingest-demo  prova o critério da Onda 1 (2x o mesmo arquivo → 1)"
	@echo "  make lint       shellcheck + helm lint"
	@echo "  make clean      remove artefatos locais"
	@echo ""
	@echo "Estado: Onda 1. Núcleo de domínio puro; infra e cluster ainda não existem."

setup: $(VENV_PY)

$(VENV_PY):
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r requirements-dev.txt
	@echo "venv pronto. Use: $(VENV_PY) -m pytest"

test: setup
	$(VENV_PY) -m pytest -q

# Critério de pronto da Onda 1 (plano-atividades §Onda 1):
# 4 entradas, 2 conteúdos distintos, 2 duplicatas → 2 objetos escritos.
# Tudo numa única invocação: os adaptadores são em memória, então o estado não
# sobrevive entre processos. Repetir o comando provaria cache, não idempotência.
ingest-demo: setup
	@tmp=$$(mktemp -d); \
	printf 'documento um\n' > "$$tmp/a.txt"; \
	printf 'documento um\n' > "$$tmp/a-copia.txt"; \
	printf 'outro conteudo\n' > "$$tmp/b.md"; \
	echo "--- a.txt, a-copia.txt (mesmo conteudo), b.md, a.txt de novo ---"; \
	PYTHONPATH=src $(VENV_PY) -m lakecore --origem demo \
		"$$tmp/a.txt" "$$tmp/a-copia.txt" "$$tmp/b.md" "$$tmp/a.txt"; \
	echo ""; \
	echo "esperado: aceitos=2 iguais=2 falhas=0 objetos=2"; \
	rm -rf "$$tmp"

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

# `make ci | tail` faz o shell enxergar o exit code do `tail`, não o do `make`:
# um CI vermelho passava despercebido atrás de um pipe. Este alvo existe para
# ser o único gate de push.
ci-check: setup
	@set -o pipefail; \
	$(MAKE) --no-print-directory ci 2>&1 || { \
		status=$$?; \
		echo ""; \
		echo "!!! CI FALHOU (exit $$status) — NÃO fazer push !!!"; \
		exit $$status; \
	}

clean:
	rm -rf $(VENV) .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
