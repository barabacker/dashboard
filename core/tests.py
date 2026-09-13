from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.admin import plural


class PluralTests(TestCase):
    def test_russian_forms(self):
        forms = ("группа", "группы", "групп")
        cases = {
            1: "группа",
            2: "группы",
            4: "группы",
            5: "групп",
            11: "групп",
            21: "группа",
            112: "групп",
            1002: "группы",
        }
        for number, expected in cases.items():
            with self.subTest(number=number):
                self.assertEqual(plural(number, forms), expected)


class AdminAccessTests(TestCase):
    def test_login_page_available(self):
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_root_redirects_to_admin(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/")


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin", "admin@example.com", "pass12345")
        User.objects.create_user("editor", "editor@example.com", "pass12345", is_active=False)
        Group.objects.create(name="Редакторы")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_dashboard_renders_kpi(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)

        titles = [card["title"] for card in response.context["kpi"]]
        self.assertEqual(titles, ["Пользователей", "С доступом в админку", "Групп", "Входов за неделю"])

    def test_kpi_counts_match_database(self):
        response = self.client.get(reverse("admin:index"))
        kpi = {card["title"]: card["metric"] for card in response.context["kpi"]}

        self.assertEqual(kpi["Пользователей"], 2)
        self.assertEqual(kpi["С доступом в админку"], 1)
        self.assertEqual(kpi["Групп"], 1)

    def test_user_changelist_renders(self):
        response = self.client.get(reverse("admin:auth_user_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")

    def test_group_changelist_renders(self):
        response = self.client.get(reverse("admin:auth_group_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Редакторы")
