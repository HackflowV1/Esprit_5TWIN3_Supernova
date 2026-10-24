from django.utils.translation import gettext_lazy as _
"""Shared identity, skills, contextual roles and sponsor representation."""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from core.validators import validate_image_size


class User(AbstractUser):
    """Original AbstractUser retained; business roles live in RoleAssignment."""

    class Meta:
        verbose_name = _('Utilisateur')
        verbose_name_plural = _('Utilisateurs')
        permissions = [('create_hackathon', _('Peut créer un hackathon'))]
        constraints = [models.UniqueConstraint(Lower('email'), condition=~models.Q(email=''), name='user_email_ci_unique')]

    def __str__(self):
        return self.username


class Profile(models.Model):
    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='profile')
    biography = models.TextField(blank=True)
    university = models.CharField(max_length=200, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, validators=[validate_image_size])
    interests = models.TextField(blank=True)

    def __str__(self):
        return str(self.user)


class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), name='skill_name_ci_unique')]

    def __str__(self):
        return self.name


class UserSkill(models.Model):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='user_skills')
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name='user_skills')
    level = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])
    experience = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'skill'], name='unique_user_skill'),
            models.CheckConstraint(condition=models.Q(level__gte=1, level__lte=5), name='skill_level_range'),
        ]

    def __str__(self):
        return f'{self.skill} ({self.level}/5)'


class Role(models.TextChoices):
    ORGANIZER = 'ORGANIZER', _('Organisateur')
    PARTICIPANT = 'PARTICIPANT', _('Participant')
    JURY = 'JURY', _('Juré')
    MENTOR = 'MENTOR', _('Mentor')
    SPONSOR_REPRESENTATIVE = 'SPONSOR_REPRESENTATIVE', _('Représentant sponsor')


class AssignmentStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', _('Actif')
    REVOKED = 'REVOKED', _('Retiré')


class RoleAssignment(models.Model):
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='role_assignments')
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='role_assignments')
    role = models.CharField(max_length=30, choices=Role.choices)
    status = models.CharField(max_length=10, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_roles')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'hackathon', 'role'], name='unique_context_role')]

    def clean(self):
        super().clean()
        if self.role == Role.PARTICIPANT and self.status == AssignmentStatus.REVOKED and self.user_id and self.hackathon_id:
            from teams.models import Registration
            if Registration.objects.filter(user_id=self.user_id, hackathon_id=self.hackathon_id, status=Registration.Status.ACCEPTED).exists():
                raise ValidationError(_('Annulez d’abord l’inscription depuis la gestion des participants.'))
        if self.pk and self.role == Role.ORGANIZER and self.status == AssignmentStatus.REVOKED:
            if not RoleAssignment.objects.filter(hackathon_id=self.hackathon_id, role=Role.ORGANIZER,
                    status=AssignmentStatus.ACTIVE).exclude(pk=self.pk).exists():
                raise ValidationError(_('Le dernier organisateur actif ne peut pas être retiré.'))
        incompatible = {Role.PARTICIPANT: Role.JURY, Role.JURY: Role.PARTICIPANT}
        if self.status == AssignmentStatus.ACTIVE and self.role in incompatible and self.hackathon_id and self.user_id:
            if RoleAssignment.objects.filter(user_id=self.user_id, hackathon_id=self.hackathon_id,
                    role=incompatible[self.role], status=AssignmentStatus.ACTIVE).exclude(pk=self.pk).exists():
                raise ValidationError(_('Participant et juré sont incompatibles dans le même hackathon.'))

    def __str__(self):
        return f'{self.user} / {self.hackathon} / {self.get_role_display()}'


class SponsorMembership(models.Model):
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='sponsor_memberships')
    organization = models.ForeignKey('hackathons.SponsorOrganization', on_delete=models.PROTECT, related_name='memberships')
    status = models.CharField(max_length=10, choices=AssignmentStatus.choices, default=AssignmentStatus.ACTIVE)
    can_propose_challenges = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'organization'], name='unique_sponsor_membership')]


class RoleAssignmentHistory(models.Model):
    assignment = models.ForeignKey(RoleAssignment, on_delete=models.PROTECT, related_name='history')
    actor = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    previous_status = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=10)
    timestamp = models.DateTimeField(auto_now_add=True)
