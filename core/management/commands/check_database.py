from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = 'Verify HackFlow database identity without exposing credentials.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql' or connection.settings_dict['NAME'] != 'hackflow_db':
            raise CommandError('Expected PostgreSQL hackflow_db.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database()')
            if cursor.fetchone()[0] != 'hackflow_db':
                raise CommandError('Database identity mismatch.')
        if connection.settings_dict['TEST']['NAME'] != 'test_hackflow_db':
            raise CommandError('Expected separate test_hackflow_db.')
        self.stdout.write(self.style.SUCCESS('Verified: hackflow_db; test target: test_hackflow_db.'))
