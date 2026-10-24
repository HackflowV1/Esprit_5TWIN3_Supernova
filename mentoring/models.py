from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.models import AssignmentStatus, Role, RoleAssignment, Skill
from hackathons.models import EventPhase, ValidatedModel


def local_label(value):
    return f'{timezone.localtime(value):%d/%m/%Y %H:%M}'


def development_phase(event):
    return event.phases.filter(kind=EventPhase.Kind.DEVELOPMENT).first()


def check_inside_development(event, start, end, message):
    phase = development_phase(event)
    if phase is None:
        raise ValidationError(_('Ce hackathon n’a pas de phase de développement.'))
    if start < phase.start or end > phase.end:
        raise ValidationError(message % {'start': local_label(phase.start), 'end': local_label(phase.end)})


class MentorExpertise(ValidatedModel):
   
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mentor_expertises')
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='mentor_expertises')
    level = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])
    description = models.TextField(blank=True, max_length=500)

    class Meta:
        ordering = ['user__username', '-level', 'skill__name']
        verbose_name = _('Expertise de mentor')
        verbose_name_plural = _('Expertises de mentors')
        constraints = [
            models.UniqueConstraint(fields=['user', 'skill'], name='unique_mentor_skill'),
            models.CheckConstraint(condition=models.Q(level__gte=1, level__lte=5), name='mentor_level_range'),
        ]

    def clean(self):
        super().clean()
        if self.user_id and not RoleAssignment.objects.filter(
                user_id=self.user_id, role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError({'user': _('Seul un mentor (rôle actif dans au moins un hackathon) peut déclarer une expertise.')})

    def __str__(self):
        return f'{self.user} · {self.skill} ({self.level}/5)'


class MentorSlotQuerySet(models.QuerySet):
    def published(self):
        return self.filter(withdrawn_at__isnull=True)

    def available(self):
        return self.published().exclude(sessions__status='BOOKED')


class MentorSlot(ValidatedModel):
   
    MIN_MINUTES = 15
    MAX_MINUTES = 120

    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='mentor_slots')
    mentor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='mentor_slots')
    start = models.DateTimeField()
    end = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MentorSlotQuerySet.as_manager()

    class Meta:
        ordering = ['start']
        verbose_name = _('Créneau de mentorat')
        verbose_name_plural = _('Créneaux de mentorat')
        indexes = [models.Index(fields=['mentor', 'start'], name='slot_mentor_start_idx')]
        constraints = [models.CheckConstraint(condition=models.Q(start__lt=models.F('end')), name='slot_dates_order')]

    @property
    def duration_minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def is_published(self):
        return self.withdrawn_at is None

    @property
    def is_booked(self):
        return any(session.status == 'BOOKED' for session in self.sessions.all())

    @property
    def availability(self):
        if not self.is_published:
            return 'WITHDRAWN'
        return 'BOOKED' if self.is_booked else 'AVAILABLE'

    @property
    def availability_label(self):
        return {'WITHDRAWN': _('Annulé'), 'BOOKED': _('Réservé'), 'AVAILABLE': _('Disponible')}[self.availability]

    def clean(self):
        super().clean()
        if self.withdrawn_at is not None:
            return  # a withdrawal must always be possible
        if not (self.start and self.end and self.hackathon_id and self.mentor_id):
            return
        if self.start >= self.end:
            raise ValidationError(_('Le début du créneau doit précéder sa fin.'))
        if not self.MIN_MINUTES <= self.duration_minutes <= self.MAX_MINUTES:
            raise ValidationError(_('Un créneau dure entre %(min)s minutes et %(max)s heures.') % {
                'min': self.MIN_MINUTES, 'max': self.MAX_MINUTES // 60})
        event = self.hackathon
        if event.status == 'ARCHIVED':
            raise ValidationError(_('Édition archivée : modification interdite.'))
        check_inside_development(event, self.start, self.end,
            _('Le créneau doit se situer pendant la phase de développement (%(start)s → %(end)s).'))
        if not RoleAssignment.objects.filter(user_id=self.mentor_id, hackathon_id=self.hackathon_id,
                role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError(_('Rôle mentor actif requis dans ce hackathon.'))
        if MentorSlot.objects.published().filter(mentor_id=self.mentor_id, start__lt=self.end, end__gt=self.start).exclude(
                pk=self.pk).exists():
            raise ValidationError(_('Ce créneau chevauche un autre de vos créneaux.'))
        if Workshop.objects.filter(trainer_id=self.mentor_id, status=Workshop.Status.PUBLISHED,
                start__lt=self.end, end__gt=self.start).exists():
            raise ValidationError(_('Vous animez un atelier à cette heure-là.'))

    def __str__(self):
        return f'{self.mentor} · {local_label(self.start)}–{timezone.localtime(self.end):%H:%M}'


class Workshop(ValidatedModel):
    class Status(models.TextChoices):
        PUBLISHED = 'PUBLISHED', _('Publié')
        CANCELLED = 'CANCELLED', _('Annulé')

    MIN_MINUTES = 15
    MAX_MINUTES = 240
    MAX_CAPACITY = 500

    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='workshops')
    trainer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workshops')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(MAX_CAPACITY)])
    start = models.DateTimeField()
    end = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    url = models.URLField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PUBLISHED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start']
        verbose_name = _('Atelier')
        verbose_name_plural = _('Ateliers')
        indexes = [models.Index(fields=['trainer', 'start'], name='workshop_trainer_start_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(start__lt=models.F('end')), name='workshop_dates_order'),
            models.CheckConstraint(condition=models.Q(capacity__gte=1), name='workshop_capacity_min'),
        ]

    @property
    def duration_minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    def clean(self):
        super().clean()
        if self.status == self.Status.CANCELLED:
            return  # a cancellation must always be possible
        if not (self.start and self.end and self.hackathon_id and self.trainer_id):
            return
        if self.start >= self.end:
            raise ValidationError(_('Le début de l’atelier doit précéder sa fin.'))
        if not self.MIN_MINUTES <= self.duration_minutes <= self.MAX_MINUTES:
            raise ValidationError(_('Un atelier dure entre %(min)s minutes et %(max)s heures.') % {
                'min': self.MIN_MINUTES, 'max': self.MAX_MINUTES // 60})
        if not (self.location.strip() or self.url):
            raise ValidationError(_('Indiquez une salle, un lien en ligne, ou les deux.'))
        event = self.hackathon
        if event.status == 'ARCHIVED':
            raise ValidationError(_('Édition archivée : modification interdite.'))
        check_inside_development(event, self.start, self.end,
            _('L’atelier doit se situer pendant la phase de développement (%(start)s → %(end)s).'))
        if not RoleAssignment.objects.filter(user_id=self.trainer_id, hackathon_id=self.hackathon_id,
                role=Role.MENTOR, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError(_('Le formateur doit avoir le rôle mentor actif dans ce hackathon.'))
        if Workshop.objects.filter(trainer_id=self.trainer_id, start__lt=self.end, end__gt=self.start).exclude(
                status=self.Status.CANCELLED).exclude(pk=self.pk).exists():
            raise ValidationError(_('Le formateur anime déjà un autre atelier à cette heure-là.'))
        if MentoringSession.objects.filter(slot__mentor_id=self.trainer_id, status=MentoringSession.Status.BOOKED,
                slot__start__lt=self.end, slot__end__gt=self.start).exists():
            raise ValidationError(_('Le formateur a déjà un rendez-vous de mentorat à cette heure-là.'))

    def get_absolute_url(self):
        return reverse('mentoring:workshop-detail', kwargs={'pk': self.pk})

    def __str__(self):
        return self.title


class SupportRequest(ValidatedModel):
   
    class Priority(models.TextChoices):
        LOW = 'LOW', _('Faible')
        NORMAL = 'NORMAL', _('Normale')
        HIGH = 'HIGH', _('Élevée')
        CRITICAL = 'CRITICAL', _('Critique')

    class Status(models.TextChoices):
        OPEN = 'OPEN', _('Ouverte')
        BOOKED = 'BOOKED', _('Rendez-vous réservé')
        IN_PROGRESS = 'IN_PROGRESS', _('Accompagnement en cours')
        RESOLVED = 'RESOLVED', _('Résolue')
        CANCELLED = 'CANCELLED', _('Annulée')

    ACTIVE_STATUSES = (Status.OPEN, Status.BOOKED, Status.IN_PROGRESS)

    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='support_requests')
    team = models.ForeignKey('teams.Team', on_delete=models.PROTECT, related_name='support_requests')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='support_requests')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, null=True, blank=True, related_name='support_requests')
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Demande d’aide')
        verbose_name_plural = _('Demandes d’aide')
        indexes = [models.Index(fields=['team', 'status'], name='request_team_status_idx'),
                   models.Index(fields=['hackathon', 'priority'], name='request_event_priority_idx')]

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def status_badge(self):
        return {'OPEN': 'proposed', 'BOOKED': 'ongoing', 'IN_PROGRESS': 'approved', 'RESOLVED': 'published', 'CANCELLED': 'withdrawn'}[self.status]

    @property
    def priority_badge(self):
        return self.priority.lower()

    def get_absolute_url(self):
        return reverse('mentoring:support-detail', kwargs={'pk': self.pk})

    def clean(self):
        super().clean()
        if self.team_id and self.hackathon_id and self.team.hackathon_id != self.hackathon_id:
            raise ValidationError(_('L’équipe doit appartenir au même hackathon.'))
        if not (self.subject or '').strip():
            raise ValidationError({'subject': _('Indiquez le sujet de votre demande.')})

    def __str__(self):
        return self.subject


class MentoringSession(ValidatedModel):
   
    class Status(models.TextChoices):
        BOOKED = 'BOOKED', _('Réservée')
        COMPLETED = 'COMPLETED', _('Terminée')
        CANCELLED = 'CANCELLED', _('Annulée')

    request = models.ForeignKey(SupportRequest, on_delete=models.PROTECT, related_name='sessions')
    slot = models.ForeignKey(MentorSlot, on_delete=models.PROTECT, related_name='sessions')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOOKED)
    booked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='booked_sessions')
    report = models.TextField(blank=True)  # compte rendu, shared with the team
    private_notes = models.TextField(blank=True)  # visible by the mentor and the organizers only
    completed_at = models.DateTimeField(null=True, blank=True)
    feedback_rating = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    feedback_comment = models.TextField(blank=True)
    feedback_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-slot__start']
        verbose_name = _('Séance de mentorat')
        verbose_name_plural = _('Séances de mentorat')
        constraints = [
            models.UniqueConstraint(fields=['slot'], condition=Q(status='BOOKED'), name='m4_one_booked_session_per_slot'),
            models.UniqueConstraint(fields=['request'], condition=Q(status='BOOKED'), name='m4_one_booked_session_per_request'),
            models.CheckConstraint(condition=Q(feedback_rating__isnull=True) | Q(feedback_rating__gte=1, feedback_rating__lte=5),
                name='m4_feedback_rating_range'),
        ]

    @property
    def team(self):
        return self.request.team

    @property
    def mentor(self):
        return self.slot.mentor

    @property
    def status_badge(self):
        return {'BOOKED': 'ongoing', 'COMPLETED': 'published', 'CANCELLED': 'withdrawn'}[self.status]

    def get_absolute_url(self):
        return reverse('mentoring:session-detail', kwargs={'pk': self.pk})

    @property
    def hackathon(self):
        return self.slot.hackathon

    def clean(self):
        super().clean()
        if not (self.request_id and self.slot_id):
            return
        if self.request.hackathon_id != self.slot.hackathon_id:
            raise ValidationError(_('La demande et le créneau doivent appartenir au même hackathon.'))
        if self.status != self.Status.BOOKED:
            return
        if self.slot.withdrawn_at is not None:
            raise ValidationError(_('Ce créneau n’est plus proposé.'))
        if self.request.team.memberships.filter(ended_at__isnull=True, registration__user_id=self.slot.mentor_id).exists():
            raise ValidationError(_('Un mentor ne peut pas accompagner sa propre équipe.'))
        if MentoringSession.objects.filter(request__team_id=self.request.team_id, status=self.Status.BOOKED,
                slot__start__lt=self.slot.end, slot__end__gt=self.slot.start).exclude(pk=self.pk).exists():
            raise ValidationError(_('Votre équipe a déjà un rendez-vous à cette heure-là.'))
        if Workshop.objects.filter(trainer_id=self.slot.mentor_id, status=Workshop.Status.PUBLISHED,
                start__lt=self.slot.end, end__gt=self.slot.start).exists():
            raise ValidationError(_('Ce mentor anime un atelier à cette heure-là.'))

    def __str__(self):
        return f'{self.request} · {self.slot}'


class WorkshopRegistration(ValidatedModel):
   

    class Status(models.TextChoices):
        REGISTERED = 'REGISTERED', _('Inscrit')
        CANCELLED = 'CANCELLED', _('Annulée')

    class Attendance(models.TextChoices):
        UNKNOWN = 'UNKNOWN', _('Non renseignée')
        PRESENT = 'PRESENT', _('Présent')
        ABSENT = 'ABSENT', _('Absent')

    workshop = models.ForeignKey(Workshop, on_delete=models.PROTECT, related_name='registrations')
    registration = models.ForeignKey('teams.Registration', on_delete=models.PROTECT, related_name='workshop_registrations')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REGISTERED)
    attendance = models.CharField(max_length=10, choices=Attendance.choices, default=Attendance.UNKNOWN)
    attendance_marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    attendance_marked_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = _('Inscription à un atelier')
        verbose_name_plural = _('Inscriptions aux ateliers')
        constraints = [models.UniqueConstraint(fields=['workshop', 'registration'], name='m4_one_workshop_registration')]

    def clean(self):
        super().clean()
        if not (self.workshop_id and self.registration_id):
            return
        if self.registration.hackathon_id != self.workshop.hackathon_id:
            raise ValidationError(_('L’inscription et l’atelier doivent appartenir au même hackathon.'))
        if self.status == self.Status.REGISTERED and self.registration.status != 'ACCEPTED':
            raise ValidationError(_('Une inscription acceptée au hackathon est requise.'))

    def __str__(self):
        return f'{self.registration.user} → {self.workshop}'


class M4History(models.Model):
    """Minimal audit trail of M4: who did what, on which object, with the useful change."""

    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='m4_history')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    action = models.CharField(max_length=60)  # stable code, e.g. 'request.opened'
    object_type = models.CharField(max_length=40)
    object_id = models.PositiveBigIntegerField()
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp', '-id']
        verbose_name = _('Historique M4')
        verbose_name_plural = _('Historique M4')
        indexes = [models.Index(fields=['hackathon', 'timestamp'], name='m4hist_event_time_idx'),
                   models.Index(fields=['object_type', 'object_id'], name='m4hist_object_idx')]

    ACTION_LABELS = {
        'request.opened': _('Demande ouverte'), 'request.cancelled': _('Demande annulée'),
        'slot.published': _('Créneau publié'), 'slot.updated': _('Créneau modifié'), 'slot.withdrawn': _('Créneau annulé'),
        'workshop.published': _('Atelier publié'), 'workshop.updated': _('Atelier modifié'), 'workshop.cancelled': _('Atelier annulé'),
        'request.resolved': _('Problème résolu'), 'request.reopened': _('Demande rouverte'),
        'session.booked': _('Rendez-vous réservé'), 'session.cancelled': _('Rendez-vous annulé'),
        'session.completed': _('Séance terminée'), 'session.report_updated': _('Compte rendu mis à jour'),
        'session.feedback': _('Retour de l’équipe'),
        'workshop.registered': _('Inscription à l’atelier'), 'workshop.unregistered': _('Inscription annulée'),
        'workshop.attendance': _('Présence relevée'),
    }

    @property
    def label(self):
        return self.ACTION_LABELS.get(self.action, self.action)

    def __str__(self):
        return f'{self.action} · {self.object_type}#{self.object_id}'
