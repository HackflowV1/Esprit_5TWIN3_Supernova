"""Opt-in URL composition without modifying the shared URL configuration."""
from django.urls import include, path
from config.urls import urlpatterns as shared_patterns

urlpatterns = [path('projects/', include('projects.urls')), *shared_patterns]
