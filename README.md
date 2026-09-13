# Dashboard

Django-проект с админкой на [Unfold](https://unfoldadmin.com/). Стартовый каркас:
настроенная тема и оформленные пользователи с группами. Доменных моделей пока
нет — они добавляются в приложение `core`.

## Стек

| | |
|---|---|
| Django | 5.2 |
| django-unfold | 0.91 |
| БД | SQLite (файл `db.sqlite3`) |
| Очередь и расписания | [Django-Q2](https://django-q2.readthedocs.io/) — брокером служит сама БД |
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

## Docker

Вариант без установки Python и uv на машину — и способ поднять обработчик задач
на Windows, где `qcluster` нативно не поддерживается.

```bash
docker compose up -d --build     # или make docker-up
docker compose run --rm web python manage.py createsuperuser
```

Админка: http://127.0.0.1:8000/admin/ — порт меняется переменной `PORT`.

Три сервиса: `migrate` прогоняет миграции и завершается, затем стартуют `web`
(Django) и `tasks` (`qcluster` — очередь и планировщик). Миграции вынесены
в отдельный шаг намеренно: у SQLite один писатель, и параллельный `migrate`
из двух контейнеров может встать на блокировке.

```bash
make docker-logs         # логи всех сервисов
make docker-down         # остановить; том с базой остаётся
docker compose down -v   # остановить и удалить базу
```

Код прокинут внутрь контейнера томом, поэтому правки видны без пересборки —
образ нужно пересобирать только при изменении зависимостей (`uv.lock`).
Виртуальное окружение лежит в `/venv`, вне `/app`, чтобы bind-mount его не перекрывал.
База — в именованном томе по пути `/data/db.sqlite3` (переменная `DJANGO_DB_PATH`),
общем для `web` и `tasks`.

## Команды

`make help` покажет список. Основное:

| Команда | Что делает |
|---|---|
| `make install` / `make sync` | зависимости: по локу / строго по локу, без перерешения |
| `make lock` / `make upgrade` | пересобрать лок / поднять версии в пределах ограничений |
| `make run` | сервер разработки, порт меняется через `PORT=8080` |
| `make tasks` | обработчик задач: очередь и расписание в одном процессе |
| `make migrate` / `make migrations` | применить / создать миграции |
| `make test` | тесты |
| `make lint` / `make fmt` | проверить / отформатировать код (ruff) |
| `make check` | `manage.py check` + проверка несозданных миграций |
| `make ci` | всё, что гоняет CI: lint + check + test |
| `make clean` / `make distclean` | убрать кэши / ещё и venv с базой |
| `make docker-up` / `make docker-down` | поднять / остановить всё в Docker |
| `make docker-build` / `make docker-logs` | пересобрать образ / смотреть логи |
| `make docker-superuser` / `make docker-shell` | суперпользователь / shell в контейнере |

## Структура

```
.env.example         шаблон переменных окружения
Dockerfile           образ на базе uv, зависимости строго по uv.lock
compose.yaml         сервисы migrate, web и tasks, общий том с базой
config/settings.py   настройки проекта и словарь UNFOLD (сайдбар, цвета, тема)
config/urls.py       / → редирект на /admin/
core/admin.py        оформленные UserAdmin и GroupAdmin, бейдж окружения
core/models.py       место для доменных моделей
core/tasks.py        задачи: одноразовая и по расписанию
core/migrations/0001_session_cleanup_schedule.py   заводит расписание очистки сессий
core/management/commands/run_task.py   поставить задачу в очередь из консоли
core/tests.py        тесты доступа и рендера страниц админки
core/tests_tasks.py  тесты задач и расписания
templates/           переопределения шаблонов админки, если понадобятся
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

**Сайдбар** задаётся вручную в `UNFOLD["SIDEBAR"]["navigation"]` — новые разделы
нужно дописывать туда, автоматически они не появляются.

## Фоновые задачи

Очередь и планировщик — [Django-Q2](https://django-q2.readthedocs.io/). Брокером
служит сама база: внешних сервисов не нужно, а задачи, расписания и история
запусков лежат в БД и видны в админке (раздел «Задачи»).

```bash
make run      # Django
make tasks    # обработчик задач (qcluster): воркеры + планировщик
```

**Что видно в админке**

| Раздел | Что показывает |
|---|---|
| Расписания | периодические задачи: cron или интервал, следующий и последний запуск; тут же создаются и правятся |
| Выполненные | история успешных запусков с результатом (хранятся последние `save_limit`) |
| Упавшие | упавшие задачи с полным трейсбеком |
| В очереди | что ждёт выполнения прямо сейчас |

**Одноразовая задача** — `core.tasks.say_hello`:

```python
from django_q.tasks import async_task

async_task("core.tasks.say_hello", "Пётр")                    # в очередь
async_task("core.tasks.say_hello", "Пётр", hook="core.tasks.on_done")  # с колбэком
```

```bash
make run-task ARGS="say_hello --name Пётр"      # или напрямую:
uv run manage.py run_task say_hello --name Пётр
uv run manage.py run_task say_hello --now       # выполнить тут же, без очереди
```

**Разовые задачи** бывают двух видов:

```python
from django.utils import timezone
from django_q.models import Schedule
from django_q.tasks import async_task, schedule

# выполнить как можно скорее — просто ставим в очередь
async_task("core.tasks.say_hello", "Пётр")

# выполнить в заданное время: расписание типа ONCE,
# после запуска оно удаляется само (repeats=-1)
schedule(
    "core.tasks.say_hello",
    "Пётр",
    name="Разовое напоминание",
    schedule_type=Schedule.ONCE,
    next_run=timezone.now() + timezone.timedelta(hours=3),
    repeats=-1,
)
```

То же самое руками: «Расписания» → «Добавить», тип «Однократно», время запуска.

**Кнопка «Запустить сейчас»** — в списке расписаний у каждой строки есть меню
(три точки) с действием «Запустить сейчас», такая же кнопка есть на странице
расписания. Она ставит задачу в очередь немедленно, с теми же аргументами,
и **не сдвигает** плановый `next_run`. У упавших задач по аналогии есть
«Перезапустить».

Реализованы Unfold-действиями в `core/admin.py`:

```python
@admin.register(Schedule)
class ScheduleAdmin(BaseScheduleAdmin, ModelAdmin):
    actions_row = ("run_now",)      # кнопка в строке списка
    actions_detail = ("run_now",)   # и на странице объекта

    @action(description="Запустить сейчас", icon="play_arrow")
    def run_now(self, request, object_id):
        ...
```

**Задача по расписанию** — `core.tasks.cleanup_expired_sessions`, чистит протухшие
сессии каждый час в :30. Расписание заводит миграция `core/0001`, дальше оно живёт
в БД: cron меняется в админке, перезапуск обработчика не нужен.

Задачи — обычные функции в `core/tasks.py`, в очередь ставятся по строковому пути
`"core.tasks.имя"`. Надёжность настраивается в `Q_CLUSTER` (`config/settings.py`):
`timeout` снимает зависшую задачу, `retry` возвращает её в очередь,
`max_attempts` ограничивает число попыток.

### Windows

В классификаторах django-q2 заявлены только POSIX и macOS: `qcluster` использует
многопроцессность и на Windows официально не поддерживается. Для разработки на
Windows есть синхронный режим — задачи выполняются сразу в вызывающем процессе,
обработчик не нужен:

```powershell
$env:Q_SYNC = "1"
```

Полноценный `qcluster` — на Linux: сервер, WSL2 или **Docker** (см. раздел выше;
это самый простой путь на Windows). Планировщик при `Q_SYNC=1` не работает —
периодические задачи там не запускаются.

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

Настройки читаются из переменных окружения. Локально удобнее держать их в `.env`:

```bash
cp .env.example .env
```

Файл в git не попадает (`.env.example` — попадает, это шаблон). Читает его
`load_env_file()` в `config/settings.py` — без внешних зависимостей. Правила:
переменная, уже заданная в окружении, побеждает файл; при дубле ключа в файле
побеждает последняя строка; строки с `#` и пустые игнорируются, кавычки снимаются.

`docker compose` подхватывает тот же `.env` сам — и для подстановки `${...}`
в `compose.yaml`, и как `env_file` внутри контейнеров (если файла нет, всё работает
на значениях по умолчанию).

| Переменная | По умолчанию |
|---|---|
| `DJANGO_SECRET_KEY` | небезопасный ключ для разработки |
| `DJANGO_DEBUG` | `1` |
| `DJANGO_ALLOWED_HOSTS` | `*` |
| `Q_SYNC` | `0` — задачи идут в очередь; `1` — выполняются синхронно |
| `DJANGO_DB_PATH` | `db.sqlite3` в корне проекта; в Docker — `/data/db.sqlite3` |
| `PORT` | `8000` — порт, на котором админка доступна на хосте (Docker и `make run`) |

Перед деплоем обязательно задать свой `DJANGO_SECRET_KEY`, выключить `DJANGO_DEBUG`
и перечислить реальные хосты в `DJANGO_ALLOWED_HOSTS`.

## Зависимости

Добавить пакет: `uv add <пакет>` (в dev-группу: `uv add --dev <пакет>`) — uv сам
обновит `pyproject.toml`, `uv.lock` и окружение. Удалить: `uv remove <пакет>`.
`uv.lock` коммитится, `.venv/` — нет.

## Что дальше

- Доменные модели в `core` (или отдельными приложениями) + их `ModelAdmin`.
- Свой дашборд на главной, когда будет что показывать: шаблон
  `templates/admin/index.html` плюс `UNFOLD["DASHBOARD_CALLBACK"]`.
- Русская локаль для Unfold: часть строк интерфейса («Type to search», «Filters»)
  остаётся английской, лечится собственным `.po`-файлом.
- Гео-слой (SpatiaLite + GDAL + карты в формах) — рабочий вариант лежит в истории,
  коммит `d5efad7`: `git show d5efad7 --stat`.
