"""M4 — Assistance, mentorat et ateliers.

Owned by M4. Other modules only read these models through the public services of this app.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import AssignmentStatus, Role, RoleAssignment, Skill
from hackathons.models import ValidatedModel


class MentorExpertise(ValidatedModel):
    """A skill declared by a mentor, with a self-assessed level (1 to 5).

    The skill comes from the shared referential (accounts.Skill): no duplicated catalogue.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentor_expertises')
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='mentor_expertises')
    level = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])

    class Meta:
        ordering = ['user__username', '-level', 'skill__name']
        verbose_name = 'Expertise de mentor'
        verbose_name_plural = 'Expertises de mentors'
        constraints = [
            models.UniqueConstraint(fields=['user', 'skill'], name='unique_mentor_skill'),
            models.CheckConstraint(condition=models.Q(level__gte=1, level__lte=5), name='mentor_level_range'),
        ]

    def clean(self):
        super().clean()
        if self.user_id and not RoleAssignment.objects.filter(
                user_id=self.user_id, role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError({'user': 'Seul un mentor (rôle actif dans au moins un hackathon) peut déclarer une expertise.'})

    def __str__(self):
        return f'{self.user} · {self.skill} ({self.level}/5)'
