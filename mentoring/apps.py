"""
mentoring/apps.py
"""
from django.apps import AppConfig


class MentoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mentoring'
    verbose_name = 'Assistance, mentorat et ateliers'
