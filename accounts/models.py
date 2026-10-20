"""
accounts/models.py
Custom User model for HackFlow — infrastructure technique uniquement.
Les champs métier (rôles, profils) seront ajoutés dans les phases suivantes.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Modèle utilisateur personnalisé de HackFlow.
    Hérite de AbstractUser sans champs métier supplémentaires.
    Prêt pour l'extension dans les futurs modules.
    """

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'

    def __str__(self):
        return self.username
