import os
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from config.settings import load_env_file


class AdminAccessTests(TestCase):
    def test_login_page_available(self):
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 200)

    def test_index_requires_login(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_root_redirects_to_admin(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/")


class AdminPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin", "admin@example.com", "pass12345")
        User.objects.create_user("editor", "editor@example.com", "pass12345", is_active=False)
        Group.objects.create(name="Редакторы")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_index_renders(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

    def test_user_changelist_renders(self):
        response = self.client.get(reverse("admin:auth_user_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")

    def test_user_change_form_renders(self):
        response = self.client.get(reverse("admin:auth_user_change", args=[self.admin.pk]))
        self.assertEqual(response.status_code, 200)

    def test_group_changelist_renders(self):
        response = self.client.get(reverse("admin:auth_group_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Редакторы")


class EnvFileTests(TestCase):
    """Загрузчик .env из config/settings.py."""

    def _write(self, text):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_values(self):
        path = self._write('FOO=bar\nQUOTED="в кавычках"\nexport EXPORTED=1\n')
        with mock.patch.dict(os.environ, {}, clear=False):
            load_env_file(path)
            self.assertEqual(os.environ["FOO"], "bar")
            self.assertEqual(os.environ["QUOTED"], "в кавычках")
            self.assertEqual(os.environ["EXPORTED"], "1")

    def test_skips_comments_and_blank_lines(self):
        path = self._write("# комментарий\n\nKEY=value\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            load_env_file(path)
            self.assertEqual(os.environ["KEY"], "value")

    def test_environment_wins_over_file(self):
        path = self._write("ALREADY_SET=из файла\n")
        with mock.patch.dict(os.environ, {"ALREADY_SET": "из окружения"}):
            load_env_file(path)
            self.assertEqual(os.environ["ALREADY_SET"], "из окружения")

    def test_last_line_wins_on_duplicate_key(self):
        path = self._write("DUPLICATE=первое\nDUPLICATE=второе\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            load_env_file(path)
            self.assertEqual(os.environ["DUPLICATE"], "второе")

    def test_missing_file_is_not_an_error(self):
        load_env_file(Path("/nonexistent/.env"))
