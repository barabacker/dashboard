from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse


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
