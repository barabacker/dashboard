from datetime import datetime

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone
from huey.contrib.djhuey import HUEY

from core.tasks import cleanup_expired_sessions, say_hello


class ImmediateHueyMixin:
    """Huey в immediate-режиме: задачи выполняются синхронно, без консьюмера."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._was_immediate = HUEY.immediate
        HUEY.immediate = True

    @classmethod
    def tearDownClass(cls):
        HUEY.immediate = cls._was_immediate
        super().tearDownClass()


class OneOffTaskTests(ImmediateHueyMixin, TestCase):
    def test_runs_locally_without_queue(self):
        self.assertEqual(say_hello.call_local("Пётр"), "Привет, Пётр!")

    def test_runs_through_queue(self):
        result = say_hello("Мир")
        self.assertEqual(result(), "Привет, Мир!")


class ScheduledTaskTests(ImmediateHueyMixin, TestCase):
    def test_schedule_is_hourly_at_30(self):
        # validate_datetime — метод класса задачи, отвечает «пора ли запускать»
        should_run = cleanup_expired_sessions.task_class.validate_datetime
        self.assertTrue(should_run(None, datetime(2026, 1, 1, 12, 30)))
        self.assertTrue(should_run(None, datetime(2026, 1, 1, 13, 30)))
        self.assertFalse(should_run(None, datetime(2026, 1, 1, 12, 31)))

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

        self.assertEqual(cleanup_expired_sessions.call_local(), "ok")
        self.assertFalse(Session.objects.filter(pk=expired.pk).exists())
        self.assertTrue(Session.objects.filter(session_key=alive).exists())
