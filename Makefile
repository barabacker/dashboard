.DEFAULT_GOAL := help

UV ?= uv
RUN := $(UV) run
PORT ?= 8000

# На Windows пул prefork не работает (billiard падает с WinError 5),
# поэтому там воркер запускается в однопоточном режиме solo.
ifeq ($(OS),Windows_NT)
POOL ?= solo
else
POOL ?= prefork
endif

.PHONY: help install sync lock upgrade run run-task worker beat migrate migrations superuser shell \
        test check lint fmt static clean distclean ci

help: ## Показать список команд
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Поставить зависимости по uv.lock (создаст .venv)
	$(UV) sync

sync: ## То же, но строго по локу — ничего не перерешает
	$(UV) sync --locked

lock: ## Пересобрать uv.lock после правок pyproject.toml
	$(UV) lock

upgrade: ## Поднять версии зависимостей в пределах ограничений
	$(UV) lock --upgrade

worker: ## Запустить celery-воркер (нужен Redis; пул: POOL=solo|threads|prefork)
	$(RUN) celery -A config worker -l info --pool=$(POOL)

beat: ## Запустить планировщик celery beat (нужен Redis)
	$(RUN) celery -A config beat -l info

run-task: ## Поставить задачу в очередь: make run-task ARGS="say_hello --name Пётр"
	$(RUN) manage.py run_task $(ARGS)

run: ## Запустить сервер разработки (PORT=8000)
	$(RUN) manage.py runserver $(PORT)

migrate: ## Применить миграции
	$(RUN) manage.py migrate

migrations: ## Создать миграции по изменениям моделей
	$(RUN) manage.py makemigrations

superuser: ## Создать суперпользователя
	$(RUN) manage.py createsuperuser

shell: ## Django shell
	$(RUN) manage.py shell

test: ## Прогнать тесты
	$(RUN) manage.py test

check: ## Проверки Django: конфигурация и несозданные миграции
	$(RUN) manage.py check
	$(RUN) manage.py makemigrations --check --dry-run

lint: ## Проверить код линтером
	$(RUN) ruff check .
	$(RUN) ruff format --check .

fmt: ## Отформатировать код и исправить автопочинимое
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

static: ## Собрать статику в staticfiles/
	$(RUN) manage.py collectstatic --noinput

ci: lint check test ## Всё, что гоняет CI

clean: ## Удалить кэши и собранную статику
	find . -path ./.venv -prune -o -name '__pycache__' -type d -print0 | xargs -0 rm -rf
	rm -rf .ruff_cache staticfiles

distclean: clean ## Удалить ещё и venv с базой
	rm -rf .venv db.sqlite3
