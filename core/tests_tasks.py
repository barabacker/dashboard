from django.contrib.sessions.models import Session
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from core.tasks import cleanup_expired_sessions, say_hello


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class OneOffTaskTests(TestCase):
    def test_runs_directly(self):
        self.assertEqual(say_hello("Пётр"), "Привет, Пётр!")

    def test_runs_through_queue(self):
        result = say_hello.delay("Мир")
        self.assertTrue(result.successful())
        self.assertEqual(result.get(), "Привет, Мир!")


class ScheduledTaskTests(TestCase):
    def test_periodic_task_registered_by_migration(self):
        task = PeriodicTask.objects.get(name="Очистка просроченных сессий")
        self.assertEqual(task.task, "core.tasks.cleanup_expired_sessions")
        self.assertEqual(task.crontab.minute, "30")
        self.assertTrue(task.enabled)

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
