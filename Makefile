.DEFAULT_GOAL := help

VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
PORT ?= 8000

.PHONY: help venv install install-dev run migrate migrations superuser shell \
        test check lint fmt static clean distclean ci

help: ## Показать список команд
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(PYTHON):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(PYTHON) ## Создать виртуальное окружение

install: venv ## Установить зависимости проекта
	$(PIP) install -r requirements.txt

install-dev: venv ## Установить зависимости проекта и разработки
	$(PIP) install -r requirements-dev.txt

run: ## Запустить сервер разработки (PORT=8000)
	$(PYTHON) manage.py runserver $(PORT)

migrate: ## Применить миграции
	$(PYTHON) manage.py migrate

migrations: ## Создать миграции по изменениям моделей
	$(PYTHON) manage.py makemigrations

superuser: ## Создать суперпользователя
	$(PYTHON) manage.py createsuperuser

shell: ## Django shell
	$(PYTHON) manage.py shell

test: ## Прогнать тесты
	$(PYTHON) manage.py test

check: ## Проверки Django: конфигурация и несозданные миграции
	$(PYTHON) manage.py check
	$(PYTHON) manage.py makemigrations --check --dry-run

lint: ## Проверить код линтером
	$(RUFF) check .
	$(RUFF) format --check .

fmt: ## Отформатировать код и исправить автопочинимое
	$(RUFF) check --fix .
	$(RUFF) format .

static: ## Собрать статику в staticfiles/
	$(PYTHON) manage.py collectstatic --noinput

ci: lint check test ## Всё, что гоняет CI

clean: ## Удалить кэши и собранную статику
	find . -path ./$(VENV) -prune -o -name '__pycache__' -type d -print0 | xargs -0 rm -rf
	rm -rf .ruff_cache staticfiles

distclean: clean ## Удалить ещё и venv с базой
	rm -rf $(VENV) db.sqlite3
