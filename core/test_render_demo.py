from io import StringIO
from unittest.mock import patch
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from accounts.models import User
from teams.models import Team
from hackathons.models import Hackathon


@override_settings(RENDER_DEMO_MODE=True, DEBUG=False)
class RenderDemoSeedTests(TestCase):
    @patch.dict('os.environ', {'RENDER_DEMO_ADMIN_PASSWORD': 'Test-only-render-password#2026'})
    def test_initialization_and_restart_preserve_demo_work(self):
        call_command('seed_render_demo', stdout=StringIO())
        self.assertFalse(settings.DEBUG)
        self.assertTrue(User.objects.get(username='render.admin').is_superuser)
        team = Team.objects.get(hackathon__slug='campus-solidaire-2026', captain__user__username='sami')
        self.assertEqual(team.skill_needs.count(), 0)
        self.assertIn('keyboard', team.description)
        team.description = 'A team idea edited during the presentation.'
        team.save()
        counts = (User.objects.count(), Hackathon.objects.count(), Team.objects.count())
        call_command('seed_render_demo', stdout=StringIO())
        team.refresh_from_db()
        self.assertEqual(team.description, 'A team idea edited during the presentation.')
        self.assertEqual(counts, (User.objects.count(), Hackathon.objects.count(), Team.objects.count()))
