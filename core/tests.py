from django.test import SimpleTestCase
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
