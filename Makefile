SHELL := /bin/bash
.DEFAULT_GOAL := help

# `helm` vem do snap do microk8s; não há binário helm standalone neste host.
HELM ?= microk8s helm3
PYTHON ?= python3
VENV := .venv
VENV_PY := $(VENV)/bin/python

# Alvos que rodam com o cluster desligado. As ondas 0-2 não tocam infra.
.PHONY: help setup ci ci-check ci-full test test-pg test-all lint lint-sh lint-yaml lint-helm \
	ingest-demo migrate migrate-down migrate-up-down pg-up pg-down clean

help:
	@echo "datalake-doomsday-env"
	@echo ""
	@echo "  make setup      cria .venv e instala ferramentas de dev"
	@echo "  make ci         validação completa (não requer cluster)"
	@echo "  make ci-full    ci + PostgreSQL real (requer Docker)"
	@echo "  make ci-check   igual a ci, mas falha o shell se algo falhar (use em push/CI)"
	@echo "  make test       testes unitários do lakecore"
	@echo "  make ingest-demo  prova o critério da Onda 1 (2x o mesmo arquivo → 1)"
	@echo "  make pg-up      sobe PostgreSQL efêmero para os testes (porta 55432)"
	@echo "  make test-pg    battery completa contra PostgreSQL real"
	@echo "  make migrate    aplica as migrações (usa LAKECORE_DATABASE_URL)"
	@echo "  make migrate-up-down  prova upgrade -> downgrade -> upgrade"
	@echo "  make lint       shellcheck + helm lint"
	@echo "  make clean      remove artefatos locais"
	@echo ""
	@echo "Estado: Onda 2. Domínio puro + catálogo persistente; cluster ainda não existe."

setup: $(VENV_PY)

$(VENV_PY):
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r requirements-dev.txt
	@echo "venv pronto. Use: $(VENV_PY) -m pytest"

test: setup
	$(VENV_PY) -m pytest -q

# PostgreSQL efêmero. Porta 55432 para não colidir com nada de outro projeto.
# --rm garante que um container esquecido não fique ocupando espaço.
PG_PORT ?= 55432
PG_URL := postgresql+psycopg://lakecore:teste123@127.0.0.1:$(PG_PORT)/lakecore

pg-up: setup
	@docker rm -f lakecore-pg-test >/dev/null 2>&1 || true
	@docker run -d --rm --name lakecore-pg-test \
		-e POSTGRES_DB=lakecore -e POSTGRES_USER=lakecore \
		-e POSTGRES_PASSWORD=teste123 -p $(PG_PORT):5432 \
		postgres:15-alpine >/dev/null
	@for i in $$(seq 1 40); do \
		if $(VENV_PY) -c "import psycopg; \
			psycopg.connect('host=127.0.0.1 port=$(PG_PORT) dbname=lakecore user=lakecore password=teste123').close()" \
			2>/dev/null; then echo "postgres pronto"; exit 0; fi; \
		sleep 1; \
	done; \
	echo "postgres não subiu em 40s"; exit 1

pg-down:
	@docker rm -f lakecore-pg-test >/dev/null 2>&1 || true
	@echo "postgres de teste removido"

test-pg: pg-up
	@LAKECORE_TEST_PG_URL="$(PG_URL)" $(VENV_PY) -m pytest -q

test-all: test test-pg
	@echo "suíte verde em SQLite e em PostgreSQL"

# Migração real. Exige LAKECORE_DATABASE_URL no ambiente.
migrate: setup
	@PYTHONPATH=src $(VENV)/bin/alembic upgrade head

migrate-up-down: pg-up
	@echo "--- upgrade head ---"; \
	LAKECORE_DATABASE_URL="$(PG_URL)" PYTHONPATH=src $(VENV)/bin/alembic upgrade head; \
	echo "--- downgrade base ---"; \
	LAKECORE_DATABASE_URL="$(PG_URL)" PYTHONPATH=src $(VENV)/bin/alembic downgrade base; \
	echo "--- upgrade head novamente ---"; \
	LAKECORE_DATABASE_URL="$(PG_URL)" PYTHONPATH=src $(VENV)/bin/alembic upgrade head; \
	echo "ciclo de migração completo"

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

# `make ci` NÃO toca Docker de propósito: as ondas 0–2 precisam rodar com a
# infra desligada. O alvo com PostgreSQL é `ci-full`.
ci: test lint
	@PYTHONPATH=src $(VENV)/bin/python -c "import lakecore; print('lakecore importável:', lakecore.__file__)"
	@PYTHONPATH=src $(VENV)/bin/python -c "from lakecore.db import Base; print('schema:', sorted(Base.metadata.tables))"
	@echo ""
	@echo "CI concluído com sucesso."

ci-full: test-pg lint
	@PYTHONPATH=src $(VENV)/bin/python -c "from lakecore.db import Base; print('schema:', sorted(Base.metadata.tables))"
	@echo ""
	@echo "CI completo (SQLite + PostgreSQL) concluído com sucesso."

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
