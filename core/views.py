"""
core/views.py — Page de vérification technique HackFlow.
"""
import django
from django.shortcuts import render


def home(request):
    """Page d'accueil technique — confirme que Django fonctionne correctement."""
    context = {
        'django_version': django.get_version(),
    }
    return render(request, 'core/home.html', context)
