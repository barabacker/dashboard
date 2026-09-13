# Dashboard

Django-проект с админкой на [Unfold](https://unfoldadmin.com/). Стартовый каркас:
настроенная тема, кастомный дашборд, оформленные пользователи и группы.
Доменных моделей пока нет — они добавляются в приложение `core`.

## Стек

| | |
|---|---|
| Django | 5.2 |
| django-unfold | 0.91 |
| БД | SQLite (файл `db.sqlite3`) |
| Пакеты и venv | [uv](https://docs.astral.sh/uv/) — `pyproject.toml` + `uv.lock` |

Системных зависимостей нет. Нужен только `uv` — нужный Python он поставит сам.

## Запуск

```bash
make install     # uv sync: создаст .venv и поставит зависимости по локу
make migrate
make superuser
make run
```

Админка: http://127.0.0.1:8000/admin/

Без Makefile — то же самое напрямую:

```bash
uv sync
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
```

`uv run` сам поднимает окружение — активировать venv не нужно.
Если uv ещё не стоит:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                  # macOS / Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"        # Windows
```

## Команды

`make help` покажет список. Основное:

| Команда | Что делает |
|---|---|
| `make install` / `make sync` | зависимости: по локу / строго по локу, без перерешения |
| `make lock` / `make upgrade` | пересобрать лок / поднять версии в пределах ограничений |
| `make run` | сервер разработки, порт меняется через `PORT=8080` |
| `make migrate` / `make migrations` | применить / создать миграции |
| `make test` | тесты |
| `make lint` / `make fmt` | проверить / отформатировать код (ruff) |
| `make check` | `manage.py check` + проверка несозданных миграций |
| `make ci` | всё, что гоняет CI: lint + check + test |
| `make clean` / `make distclean` | убрать кэши / ещё и venv с базой |

## Структура

```
config/settings.py   настройки проекта и словарь UNFOLD (сайдбар, цвета, дашборд)
config/urls.py       / → редирект на /admin/
core/admin.py        dashboard_callback, оформленные UserAdmin и GroupAdmin
core/models.py       место для доменных моделей
core/tests.py        тесты дашборда и доступа к админке
templates/admin/index.html   дашборд на компонентах Unfold
```

## Как это настроено

**Unfold идёт первым в `INSTALLED_APPS`** — до `django.contrib.admin`, иначе его шаблоны не подхватятся.

**Своя админ-модель наследует ModelAdmin из Unfold:**

```python
from unfold.admin import ModelAdmin

@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    list_display = ("title", "created_at")
```

Для моделей, у которых уже есть готовый ModelAdmin (User, Group), миксуются оба —
см. `core/admin.py`.

**Дашборд** рисуется из `templates/admin/index.html`, данные приходят из
`core.admin.dashboard_callback` (указан в `UNFOLD["DASHBOARD_CALLBACK"]`).
Сейчас показывает метрики по пользователям; доменные метрики добавляются туда же.

**Сайдбар** задаётся вручную в `UNFOLD["SIDEBAR"]["navigation"]` — новые разделы
нужно дописывать туда, автоматически они не появляются.

## CI

GitHub Actions (`.github/workflows/ci.yml`) на каждый push в `main` и на каждый PR:

| Job | Что делает |
|---|---|
| Линтер | `uv sync --locked`, затем `ruff check` + `ruff format --check` |
| Тесты | `manage.py check`, проверка несозданных миграций, `manage.py test`, `collectstatic` на Python 3.11 / 3.12 / 3.13 |

Оба job'а ставят зависимости через `uv sync --locked`: версии берутся из `uv.lock`,
CI падает, если лок разошёлся с `pyproject.toml`. После правки зависимостей нужно
закоммитить обновлённый `uv.lock` (`make lock`).

Локально то же самое — `make ci`.

## Настройки окружения

| Переменная | По умолчанию |
|---|---|
| `DJANGO_SECRET_KEY` | небезопасный ключ для разработки |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `*` |

Перед деплоем задать все три.

## Зависимости

Добавить пакет: `uv add <пакет>` (в dev-группу: `uv add --dev <пакет>`) — uv сам
обновит `pyproject.toml`, `uv.lock` и окружение. Удалить: `uv remove <пакет>`.
`uv.lock` коммитится, `.venv/` — нет.

## Что дальше

- Доменные модели в `core` (или отдельными приложениями) + их `ModelAdmin`.
- Русская локаль для Unfold: часть строк интерфейса («Type to search», «Filters»)
  остаётся английской, лечится собственным `.po`-файлом.
- Гео-слой (SpatiaLite + GDAL + карты в формах) — рабочий вариант лежит в истории,
  коммит `d5efad7`: `git show d5efad7 --stat`.
