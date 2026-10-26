"""Initialize fictional classroom data once; keep HTTP DEBUG disabled."""
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings
from accounts.models import User
import os


class Command(BaseCommand):
    help = 'Initialize the isolated Render classroom demo once, without copying local accounts or secrets.'

    @transaction.atomic
    def handle(self, **options):
        if not getattr(settings, 'RENDER_DEMO_MODE', False):
            raise CommandError('Requires the explicit Render demo settings.')
        if User.objects.filter(username='render.admin').exists():
            self.stdout.write('Render demo already initialized; saved work preserved.')
            return
        password = os.environ.get('RENDER_DEMO_ADMIN_PASSWORD', '')
        if len(password) < 16:
            raise CommandError('Configure the generated RENDER_DEMO_ADMIN_PASSWORD first.')
        # This override applies only inside the initialization command, never in
        # the separately started Gunicorn server. Existing demo services retain
        # their permission checks and populate fresh fictional accounts only.
        with override_settings(DEBUG=True):
            call_command('seed_demo', stdout=self.stdout)
            call_command('seed_m2_sami_showcase', configure_team=True, english=True, stdout=self.stdout)
            call_command('seed_m2_skill_needs_demo', stdout=self.stdout)
            call_command('seed_m4_demo', stdout=self.stdout)
            call_command('seed_m3_demo', stdout=self.stdout)
        User.objects.create_superuser('render.admin', email='render.admin@example.test', password=password)
        self.stdout.write(self.style.SUCCESS('Render classroom demo initialized. Admin password is stored only in Render environment settings.'))
