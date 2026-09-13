from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import Schedule, Success
from django_q.tasks import async_task, fetch

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
