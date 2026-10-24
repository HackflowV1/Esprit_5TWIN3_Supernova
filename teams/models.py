"""M2 records. All writes from the UI go through teams.services."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Registration(models.Model):
    class Status(models.TextChoices):
        ACCEPTED = 'ACCEPTED', _('Acceptée')
        CANCELLED = 'CANCELLED', _('Annulée')

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='registrations')
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='registrations')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACCEPTED)
    accepted_conditions_at = models.DateTimeField(default=timezone.now)
    conditions_snapshot = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['user', 'hackathon'], name='m2_unique_registration')]

    def __str__(self):
        return f'{self.user} · {self.hackathon}'


class Team(models.Model):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='teams')
    name = models.CharField(_('Nom de l’équipe'), max_length=100)
    description = models.TextField(_('Votre idée et votre équipe'), max_length=2000, blank=True)
    captain = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name='captained_teams')
    recruiting = models.BooleanField(_('Recrutement ouvert'), default=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), 'hackathon', name='m2_unique_team_name')]

    def clean(self):
        if self.captain_id and self.captain.hackathon_id != self.hackathon_id:
            raise ValidationError(_('Le capitaine doit être inscrit au même hackathon.'))

    @property
    def member_count(self):
        return getattr(self, 'active_count', None) if hasattr(self, 'active_count') else self.memberships.filter(ended_at__isnull=True).count()

    @property
    def is_ready(self):
        return self.closed_at is None and self.hackathon.min_team_size <= self.member_count <= self.hackathon.max_team_size and not self.memberships.filter(ended_at__isnull=True).exclude(registration__status=Registration.Status.ACCEPTED).exists()

    @property
    def places_left(self):
        return max(0, self.hackathon.max_team_size - self.member_count)

    def get_absolute_url(self):
        return reverse('teams:detail', kwargs={'slug': self.hackathon.slug, 'pk': self.pk})

    def __str__(self):
        return self.name


class TeamMembership(models.Model):
    registration = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name='memberships')
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='memberships')
    joined_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['registration'], condition=Q(ended_at__isnull=True), name='m2_one_active_team')]

    def clean(self):
        if self.registration_id and self.team_id and self.registration.hackathon_id != self.team.hackathon_id:
            raise ValidationError(_('L’inscription et l’équipe doivent appartenir au même hackathon.'))
        if self.ended_at is None and self.registration_id and self.registration.status != Registration.Status.ACCEPTED:
            raise ValidationError(_('Une inscription acceptée est requise.'))


class Decision(models.TextChoices):
    PENDING = 'PENDING', _('En attente')
    ACCEPTED = 'ACCEPTED', _('Acceptée')
    DECLINED = 'DECLINED', _('Refusée')
    CANCELLED = 'CANCELLED', _('Annulée')
    EXPIRED = 'EXPIRED', _('Expirée')


class RecruitmentRecord(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name='%(class)ss')
    registration = models.ForeignKey(Registration, on_delete=models.PROTECT, related_name='%(class)ss')
    message = models.TextField(_('Message'), max_length=1000, blank=True)
    status = models.CharField(max_length=12, choices=Decision.choices, default=Decision.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['team', 'registration'], condition=Q(status='PENDING'), name='%(class)s_pending_unique')]

    def clean(self):
        if self.team_id and self.registration_id and self.team.hackathon_id != self.registration.hackathon_id:
            raise ValidationError(_('La demande doit concerner le même hackathon.'))


class TeamInvitation(RecruitmentRecord):
    expires_at = models.DateTimeField()

    @property
    def effective_status(self):
        return Decision.EXPIRED if self.status == Decision.PENDING and self.expires_at <= timezone.now() else self.status


class JoinRequest(RecruitmentRecord):
    pass


class TeamSkillNeed(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='skill_needs')
    skill = models.ForeignKey('accounts.Skill', on_delete=models.PROTECT)
    level = models.PositiveSmallIntegerField(_('Niveau souhaité'), default=2, validators=[MinValueValidator(1), MaxValueValidator(5)])
    priority = models.PositiveSmallIntegerField(_('Priorité'), choices=[(1, _('Utile')), (2, _('Importante')), (3, _('Essentielle'))], default=2)

    class Meta:
        ordering = ['-priority', 'skill__name']
        constraints = [models.UniqueConstraint(fields=['team', 'skill'], name='m2_unique_team_need'), models.CheckConstraint(condition=Q(level__gte=1, level__lte=5, priority__gte=1, priority__lte=3), name='m2_need_ranges')]


class TeamHistory(models.Model):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='team_history')
    team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True, related_name='history')
    registration = models.ForeignKey(Registration, on_delete=models.PROTECT, null=True, blank=True, related_name='history')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=40, choices=[
        ('REGISTER', _('Inscription confirmée')), ('CANCEL_REGISTRATION', _('Inscription annulée')),
        ('CREATE_TEAM', _('Équipe créée')), ('UPDATE_TEAM', _('Équipe modifiée')),
        ('JOIN_TEAM', _('Membre ajouté')), ('LEAVE_TEAM', _('Départ d’un membre')),
        ('REMOVE_MEMBER', _('Membre retiré')), ('TRANSFER_CAPTAIN', _('Capitaine transféré')),
        ('INVITE', _('Invitation envoyée')), ('APPLY', _('Candidature envoyée')),
        ('DECIDE_RECRUITMENT', _('Décision de recrutement')), ('CANCEL_RECRUITMENT', _('Demande annulée')),
        ('SAVE_SKILL_NEED', _('Besoin de compétence enregistré')), ('DELETE_SKILL_NEED', _('Besoin de compétence retiré')),
    ])
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp', '-pk']
