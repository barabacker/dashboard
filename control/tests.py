import json

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from control.models import Run, RunLog, Runner, Source
from control.services import (
    append_logs,
    claim_run,
    complete_run,
    expire_stale_runs,
    next_run_for,
    schedule_due_runs,
)


def make_source(**kwargs):
    defaults = {
        "name": "Тестовый источник",
        "slug": "test",
        "parser": "demo.numbers",
        "cron": "*/5 * * * *",
        "params": {"count": 3},
    }
    return Source.objects.create(**{**defaults, **kwargs})


class ScheduleTests(TestCase):
    def test_next_run_filled_on_save(self):
        source = make_source()
        self.assertIsNotNone(source.next_run_at)
        self.assertGreater(source.next_run_at, timezone.now())

    def test_due_source_gets_run(self):
        source = make_source(next_run_at=timezone.now() - timezone.timedelta(minutes=1))

        created = schedule_due_runs()

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].source, source)
        self.assertEqual(created[0].trigger, Run.Trigger.SCHEDULE)

        source.refresh_from_db()
        self.assertGreater(source.next_run_at, timezone.now())

    def test_not_due_source_is_skipped(self):
        make_source(next_run_at=timezone.now() + timezone.timedelta(hours=1))
        self.assertEqual(schedule_due_runs(), [])

    def test_inactive_source_is_skipped(self):
        make_source(is_active=False, next_run_at=timezone.now() - timezone.timedelta(minutes=1))
        self.assertEqual(schedule_due_runs(), [])

    def test_source_with_active_run_is_not_queued_twice(self):
        source = make_source(next_run_at=timezone.now() - timezone.timedelta(minutes=1))
        Run.objects.create(source=source, status=Run.Status.RUNNING)

        self.assertEqual(schedule_due_runs(), [])


class ClaimTests(TestCase):
    def setUp(self):
        self.runner = Runner.objects.create(name="runner-1")
        self.source = make_source()

    def test_claim_marks_run_running(self):
        run = Run.objects.create(source=self.source)

        claimed = claim_run(self.runner)

        self.assertEqual(claimed.pk, run.pk)
        self.assertEqual(claimed.status, Run.Status.RUNNING)
        self.assertEqual(claimed.runner, self.runner)
        self.assertIsNotNone(claimed.lease_expires_at)

    def test_second_claim_gets_nothing(self):
        Run.objects.create(source=self.source)
        other = Runner.objects.create(name="runner-2")

        self.assertIsNotNone(claim_run(self.runner))
        self.assertIsNone(claim_run(other))

    def test_expired_run_is_released(self):
        run = Run.objects.create(
            source=self.source,
            status=Run.Status.RUNNING,
            runner=self.runner,
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        self.assertEqual(expire_stale_runs(), 1)

        run.refresh_from_db()
        self.assertEqual(run.status, Run.Status.EXPIRED)
        self.assertIn("аренды", run.error)

        self.source.refresh_from_db()
        self.assertEqual(self.source.consecutive_failures, 1)


class LogTests(TestCase):
    def setUp(self):
        self.run = Run.objects.create(source=make_source())

    def test_entries_are_numbered_and_counted(self):
        append_logs(self.run, [{"level": "INFO", "message": "раз"}, {"level": "WARNING", "message": "два"}])
        append_logs(self.run, [{"level": "ERROR", "message": "три"}])

        self.run.refresh_from_db()
        self.assertEqual(self.run.log_lines, 3)
        self.assertEqual(self.run.warnings_count, 2)
        self.assertEqual(list(self.run.logs.values_list("seq", flat=True)), [1, 2, 3])

    def test_long_message_is_truncated(self):
        append_logs(self.run, [{"level": "INFO", "message": "я" * 9000}])

        entry = self.run.logs.get()
        self.assertLess(len(entry.message), 9000)
        self.assertTrue(entry.message.endswith("…обрезано"))

    def test_unknown_level_falls_back_to_info(self):
        append_logs(self.run, [{"level": "ЧТО-ТО", "message": "текст"}])
        self.assertEqual(self.run.logs.get().level, RunLog.Level.INFO)

    def test_line_limit_is_enforced(self):
        with self.settings(CONTROL={"MAX_LOG_LINES_PER_RUN": 5}):
            append_logs(self.run, [{"message": f"строка {i}"} for i in range(20)])

            self.run.refresh_from_db()
            self.assertEqual(self.run.log_lines, 5)
            self.assertTrue(self.run.logs.filter(message__contains="лимит").exists())


class CompleteTests(TestCase):
    def setUp(self):
        self.source = make_source(max_failures=2)
        self.run = Run.objects.create(source=self.source, status=Run.Status.RUNNING)

    def test_success_resets_failures(self):
        Source.objects.filter(pk=self.source.pk).update(consecutive_failures=1)

        complete_run(
            self.run,
            status=Run.Status.SUCCESS,
            counters={"items_total": 10, "items_new": 7, "items_updated": 3, "pages": 2},
            result_locator="s3://bucket/batch-1",
        )

        self.run.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.run.status, Run.Status.SUCCESS)
        self.assertEqual(self.run.items_total, 10)
        self.assertEqual(self.run.counters, {"pages": 2})
        self.assertEqual(self.run.result_locator, "s3://bucket/batch-1")
        self.assertEqual(self.source.consecutive_failures, 0)

    def test_failures_disable_source(self):
        complete_run(self.run, status=Run.Status.FAILED, error="таймаут")
        self.source.refresh_from_db()
        self.assertTrue(self.source.is_active)

        second = Run.objects.create(source=self.source, status=Run.Status.RUNNING)
        complete_run(second, status=Run.Status.FAILED, error="таймаут")

        self.source.refresh_from_db()
        self.assertEqual(self.source.consecutive_failures, 2)
        self.assertFalse(self.source.is_active)

    def test_completing_twice_keeps_first_result(self):
        complete_run(self.run, status=Run.Status.SUCCESS, counters={"items_total": 5})
        complete_run(self.run, status=Run.Status.FAILED, error="поздно")

        self.run.refresh_from_db()
        self.assertEqual(self.run.status, Run.Status.SUCCESS)
        self.assertEqual(self.run.items_total, 5)


class ApiTests(TestCase):
    def setUp(self):
        self.runner = Runner.objects.create(name="runner-1")
        self.source = make_source(next_run_at=timezone.now() - timezone.timedelta(minutes=1))
        self.headers = {"HTTP_X_RUNNER_TOKEN": self.runner.token}

    def post(self, url, payload=None, **extra):
        return self.client.post(url, data=json.dumps(payload or {}), content_type="application/json", **extra)

    def test_token_required(self):
        response = self.post(reverse("control:claim"))
        self.assertEqual(response.status_code, 401)

    def test_inactive_runner_rejected(self):
        Runner.objects.filter(pk=self.runner.pk).update(is_active=False)
        response = self.post(reverse("control:claim"), **self.headers)
        self.assertEqual(response.status_code, 401)

    def test_claim_returns_job_and_touches_runner(self):
        response = self.post(reverse("control:claim"), **self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()["run"]
        self.assertEqual(payload["parser"], "demo.numbers")
        self.assertEqual(payload["params"], {"count": 3})

        self.runner.refresh_from_db()
        self.assertIsNotNone(self.runner.last_seen_at)

    def test_claim_returns_null_when_nothing_to_do(self):
        Source.objects.filter(pk=self.source.pk).update(
            next_run_at=timezone.now() + timezone.timedelta(hours=1)
        )
        response = self.post(reverse("control:claim"), **self.headers)
        self.assertIsNone(response.json()["run"])

    def test_full_cycle(self):
        run_id = self.post(reverse("control:claim"), **self.headers).json()["run"]["id"]

        logs = self.post(
            reverse("control:logs", args=[run_id]),
            {"entries": [{"level": "INFO", "message": "поехали"}]},
            **self.headers,
        )
        self.assertEqual(logs.json()["accepted"], 1)

        heartbeat = self.post(reverse("control:heartbeat", args=[run_id]), **self.headers)
        self.assertIn("lease_expires_at", heartbeat.json())

        done = self.post(
            reverse("control:complete", args=[run_id]),
            {
                "status": "success",
                "counters": {"items_total": 3, "items_new": 3},
                "result_locator": "file:///data/batch.jsonl",
            },
            **self.headers,
        )

        self.assertEqual(done.json()["status"], "success")
        run = Run.objects.get(pk=run_id)
        self.assertEqual(run.status, Run.Status.SUCCESS)
        self.assertEqual(run.items_total, 3)
        self.assertEqual(run.logs.count(), 1)

    def test_foreign_run_is_not_accessible(self):
        other_runner = Runner.objects.create(name="runner-2")
        run = Run.objects.create(source=self.source, status=Run.Status.RUNNING, runner=other_runner)

        response = self.post(reverse("control:heartbeat", args=[run.pk]), **self.headers)
        self.assertEqual(response.status_code, 404)

    def test_bad_status_rejected(self):
        run_id = self.post(reverse("control:claim"), **self.headers).json()["run"]["id"]
        response = self.post(reverse("control:complete", args=[run_id]), {"status": "готово"}, **self.headers)
        self.assertEqual(response.status_code, 400)


class AdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin", "a@e.com", "pass12345")
        cls.source = make_source()

    def setUp(self):
        self.client.force_login(self.admin)

    def test_source_list_renders(self):
        response = self.client.get(reverse("admin:control_source_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Тестовый источник")

    def test_run_now_button_creates_pending_run(self):
        url = reverse("admin:control_source_run_now", args=[self.source.pk])
        response = self.client.get(url, follow=True)

        self.assertEqual(response.status_code, 200)
        run = Run.objects.get()
        self.assertEqual(run.status, Run.Status.PENDING)
        self.assertEqual(run.trigger, Run.Trigger.MANUAL)

    def test_run_page_shows_log(self):
        run = Run.objects.create(source=self.source, status=Run.Status.SUCCESS)
        append_logs(run, [{"level": "ERROR", "message": "что-то сломалось"}])

        response = self.client.get(reverse("admin:control_run_change", args=[run.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "что-то сломалось")

    def test_logs_list_renders(self):
        run = Run.objects.create(source=self.source)
        append_logs(run, [{"level": "WARNING", "message": "подозрительно"}])

        response = self.client.get(reverse("admin:control_runlog_changelist"))
        self.assertContains(response, "подозрительно")


class MaintenanceCommandTests(TestCase):
    def test_removes_old_logs_and_expires_runs(self):
        source = make_source()
        old_run = Run.objects.create(source=source, status=Run.Status.SUCCESS)
        append_logs(old_run, [{"message": "старое"}])
        RunLog.objects.update(ts=timezone.now() - timezone.timedelta(days=60))

        Run.objects.create(
            source=source,
            status=Run.Status.RUNNING,
            lease_expires_at=timezone.now() - timezone.timedelta(minutes=5),
        )

        call_command("maintenance", verbosity=0)

        self.assertEqual(RunLog.objects.count(), 0)
        self.assertTrue(Run.objects.filter(status=Run.Status.EXPIRED).exists())


class NextRunForTests(TestCase):
    def test_pipeline_creates_and_claims(self):
        runner = Runner.objects.create(name="runner-1")
        make_source(next_run_at=timezone.now() - timezone.timedelta(minutes=1))

        run = next_run_for(runner)

        self.assertIsNotNone(run)
        self.assertEqual(run.status, Run.Status.RUNNING)
        self.assertEqual(run.runner, runner)
