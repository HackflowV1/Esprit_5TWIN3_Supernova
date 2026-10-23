from django.test import SimpleTestCase, TestCase
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.core.exceptions import ImproperlyConfigured
from config.database import database_config


class DatabaseSafetyTests(SimpleTestCase):
    def test_only_hackflow_local_database_is_accepted(self):
        config = database_config('postgresql://postgres@127.0.0.1:5432/hackflow_db')
        self.assertEqual(config['NAME'], 'hackflow_db')
        self.assertEqual(config['TEST']['NAME'], 'test_hackflow_db')

    def test_other_projects_and_connection_options_rejected(self):
        urls = [
            'postgresql://postgres@127.0.0.1:5432/import_export',
            'postgresql://postgres@127.0.0.1:5432/import_export_v2',
            'sqlite:///db.sqlite3', 'postgresql://postgres@remote.example:5432/hackflow_db',
            'postgresql://postgres@127.0.0.1:5433/hackflow_db',
            'postgresql://postgres@127.0.0.1:5432/hackflow_db?options=unsafe',
            'postgresql://postgres@127.0.0.1:invalid/hackflow_db',
        ]
        for value in urls:
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                database_config(value)


class HomePageTests(TestCase):
    def test_home_is_a_public_landing_page(self):
        response = self.client.get(reverse('core:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prochains hackathons')
        self.assertContains(response, 'La prochaine édition arrive bientôt')

    def test_layout_exposes_accessibility_landmarks(self):
        response = self.client.get(reverse('core:home'))
        for fragment in ('class="skip-link"', '<main id="contenu"', '<nav id="site-nav"', 'aria-label="Navigation principale"', '<footer', '<html lang="fr">'):
            with self.subTest(fragment=fragment):
                self.assertContains(response, fragment)
        self.assertContains(response, '<h1', count=1)

    def test_login_and_signup_link_to_each_other(self):
        self.assertContains(self.client.get(reverse('accounts:login')), reverse('accounts:signup'))
        self.assertContains(self.client.get(reverse('accounts:signup')), reverse('accounts:login'))

    def test_nav_has_home_link_and_footer_has_no_copyright_line(self):
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, '>Accueil</a>')
        self.assertNotContains(response, 'Projet Django 5TWIN')
        self.assertNotContains(response, '©')

    def test_auth_pages_use_split_layout_without_custom_password_icon(self):
        for name in ('accounts:login', 'accounts:signup'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertTemplateUsed(response, 'accounts/auth.html')
                self.assertNotContains(response, 'password-toggle')

    def test_signup_errors_are_shown_under_the_fields_without_upfront_rules(self):
        page = self.client.get(reverse('accounts:signup'))
        self.assertNotContains(page, 'Votre mot de passe doit contenir')
        response = self.client.post(reverse('accounts:signup'), {
            'username': 'ab cd', 'email': 'not-an-email', 'password1': '123', 'password2': '456'})
        self.assertContains(response, 'field-error', count=3)
        weak = self.client.post(reverse('accounts:signup'), {
            'username': 'valid.name', 'email': 'ok@example.test', 'password1': '123', 'password2': '123'})
        self.assertContains(weak, 'field-error', count=1)
        self.assertContains(weak, 'trop court')


@override_settings(DEBUG=True)
class SeedDemoTests(TestCase):
    def run_seed(self, **options):
        from io import StringIO
        call_command('seed_demo', stdout=StringIO(), **options)

    def test_seed_builds_published_events_and_is_idempotent(self):
        from accounts.models import RoleAssignment, User
        from hackathons.models import Challenge, Hackathon
        owner = User.objects.create_user(username='asma02', password='x')
        self.run_seed(user='asma02')
        self.run_seed(user='asma02')
        self.assertEqual(Hackathon.objects.count(), 2)
        self.assertEqual(Hackathon.objects.filter(status='ONGOING').count(), 1)
        self.assertEqual(Hackathon.objects.filter(status='PUBLISHED').count(), 1)
        self.assertEqual(Challenge.objects.filter(status='PUBLISHED').count(), 6)
        self.assertEqual(Challenge.objects.filter(status='PROPOSED').count(), 2)
        self.assertTrue(RoleAssignment.objects.filter(user=owner, role='ORGANIZER', status='ACTIVE').count() == 2)
        self.assertEqual(User.objects.filter(username='mentor.django').count(), 1)
        self.assertContains(self.client.get(reverse('hackathons:list')), 'HackFlow Demo 2026')

    def test_seed_refuses_without_debug(self):
        from django.core.management.base import CommandError
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            self.run_seed()
