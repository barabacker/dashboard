from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import Schedule, Success
from django_q.tasks import async_task, fetch

from core.admin import enqueue_schedule
from core.tasks import cleanup_expired_sessions, say_hello


class SyncClusterMixin:
    """Задачи выполняются синхронно: кластер в тестах не запускается.

    django_q читает конфиг при импорте, поэтому override_settings на него
    не действует — переключаем Conf напрямую.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._was_sync = Conf.SYNC
        Conf.SYNC = True

    @classmethod
    def tearDownClass(cls):
        Conf.SYNC = cls._was_sync
        super().tearDownClass()


class OneOffTaskTests(SyncClusterMixin, TestCase):
    def test_runs_directly(self):
        self.assertEqual(say_hello("Пётр"), "Привет, Пётр!")

    def test_runs_through_queue(self):
        task_id = async_task("core.tasks.say_hello", "Мир", task_name="приветствие")

        task = fetch(task_id)
        self.assertTrue(task.success)
        self.assertEqual(task.result, "Привет, Мир!")
        self.assertTrue(Success.objects.filter(id=task_id).exists())


class ScheduledTaskTests(TestCase):
    def test_schedule_registered_by_migration(self):
        schedule = Schedule.objects.get(name="Очистка просроченных сессий")
        self.assertEqual(schedule.func, "core.tasks.cleanup_expired_sessions")
        self.assertEqual(schedule.schedule_type, Schedule.CRON)
        self.assertEqual(schedule.cron, "30 * * * *")

    def test_cleanup_removes_only_expired_sessions(self):
        store = self.client.session
        store["stays"] = True
        store.save()
        alive = store.session_key

        expired = Session.objects.create(
            session_key="expired-key",
            session_data="",
            expire_date=timezone.now() - timezone.timedelta(days=1),
        )

        self.assertEqual(cleanup_expired_sessions(), "ok")
        self.assertFalse(Session.objects.filter(pk=expired.pk).exists())
        self.assertTrue(Session.objects.filter(session_key=alive).exists())


class RunNowActionTests(SyncClusterMixin, TestCase):
    """Кнопка «Запустить сейчас» на расписании."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin", "admin@example.com", "pass12345")
        cls.schedule = Schedule.objects.create(
            name="Приветствие",
            func="core.tasks.say_hello",
            args="'Пётр'",
            schedule_type=Schedule.CRON,
            cron="0 9 * * *",
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_enqueue_schedule_passes_arguments(self):
        task_id = enqueue_schedule(self.schedule)

        task = fetch(task_id)
        self.assertTrue(task.success)
        self.assertEqual(task.result, "Привет, Пётр!")

    def test_button_runs_task_and_keeps_schedule(self):
        next_run_before = self.schedule.next_run

        url = reverse("admin:django_q_schedule_run_now", args=[self.schedule.pk])
        response = self.client.get(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Success.objects.filter(func="core.tasks.say_hello").exists())

        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.next_run, next_run_before)
