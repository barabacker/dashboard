.DEFAULT_GOAL := help

UV ?= uv
RUN := $(UV) run
PORT ?= 8000

.PHONY: help install sync lock upgrade run maintenance runner migrate migrations superuser shell \
        test check lint fmt static clean distclean ci \
        docker-build docker-up docker-down docker-logs docker-superuser docker-shell

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

maintenance: ## Просроченные запуски и чистка старых логов
	$(RUN) manage.py maintenance

runner: ## Запустить референсный раннер (нужен RUNNER_TOKEN)
	$(RUN) --directory runner python runner.py

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

docker-build: ## Собрать образ
	docker compose build

docker-up: ## Поднять web и обработчик задач в Docker
	docker compose up -d
	@echo "Админка: http://127.0.0.1:$(PORT)/admin/"

docker-down: ## Остановить контейнеры (том с базой остаётся)
	docker compose down

docker-logs: ## Логи всех сервисов
	docker compose logs -f

docker-superuser: ## Создать суперпользователя в контейнере
	docker compose run --rm web python manage.py createsuperuser

docker-shell: ## Shell внутри контейнера web
	docker compose run --rm web bash

clean: ## Удалить кэши и собранную статику
	find . -path ./.venv -prune -o -name '__pycache__' -type d -print0 | xargs -0 rm -rf
	rm -rf .ruff_cache staticfiles

distclean: clean ## Удалить ещё и venv с базами
	rm -rf .venv db.sqlite3
