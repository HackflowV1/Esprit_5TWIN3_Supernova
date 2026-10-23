"""M4 — Assistance, mentorat et ateliers.

Owned by M4. Other modules only read these models through the public services of this app.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

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


class MentorSlot(ValidatedModel):
    """A time range during which a mentor offers help, inside one hackathon.

    Business rules (also enforced by mentoring.services under row locks):
    - the mentor holds an active MENTOR role in that hackathon;
    - the slot lasts between 15 minutes and 2 hours and fits inside the event;
    - a mentor never has two overlapping slots, whatever the hackathon (cancelled slots do not count).
    """

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Disponible'
        BOOKED = 'BOOKED', 'Réservé'
        CANCELLED = 'CANCELLED', 'Annulé'

    MIN_MINUTES = 15
    MAX_MINUTES = 120

    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='mentor_slots')
    mentor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='mentor_slots')
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start']
        verbose_name = 'Créneau de mentorat'
        verbose_name_plural = 'Créneaux de mentorat'
        indexes = [models.Index(fields=['mentor', 'start'], name='slot_mentor_start_idx')]
        constraints = [models.CheckConstraint(condition=models.Q(start__lt=models.F('end')), name='slot_dates_order')]

    @property
    def duration_minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    def clean(self):
        super().clean()
        if self.status == self.Status.CANCELLED:
            return  # a cancellation must always be possible
        if not (self.start and self.end and self.hackathon_id and self.mentor_id):
            return
        if self.start >= self.end:
            raise ValidationError('Le début du créneau doit précéder sa fin.')
        if not self.MIN_MINUTES <= self.duration_minutes <= self.MAX_MINUTES:
            raise ValidationError(f'Un créneau dure entre {self.MIN_MINUTES} minutes et {self.MAX_MINUTES // 60} heures.')
        event = self.hackathon
        if event.status == 'ARCHIVED':
            raise ValidationError('Édition archivée : modification interdite.')
        if self.start < event.start_date or self.end > event.end_date:
            local = timezone.localtime
            raise ValidationError('Le créneau doit se situer pendant l’événement '
                f'({local(event.start_date):%d/%m/%Y %H:%M} → {local(event.end_date):%d/%m/%Y %H:%M}).')
        if not RoleAssignment.objects.filter(user_id=self.mentor_id, hackathon_id=self.hackathon_id,
                role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError('Rôle mentor actif requis dans ce hackathon.')
        if MentorSlot.objects.filter(mentor_id=self.mentor_id, start__lt=self.end, end__gt=self.start).exclude(
                status=self.Status.CANCELLED).exclude(pk=self.pk).exists():
            raise ValidationError('Ce créneau chevauche un autre de vos créneaux.')

    def __str__(self):
        local = timezone.localtime
        return f'{self.mentor} · {local(self.start):%d/%m/%Y %H:%M}–{local(self.end):%H:%M}'
