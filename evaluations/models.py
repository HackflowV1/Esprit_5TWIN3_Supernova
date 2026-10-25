"""M5 persists references to M1/M3; all business operations use services."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EvaluationCampaign(ValidatedModel):
    hackathon = models.OneToOneField('hackathons.Hackathon', on_delete=models.PROTECT, related_name='evaluation_campaign')
    rubric_validated = models.BooleanField(default=False)
    divergence_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('25'), validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(100)])
    minimum_jurors = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(divergence_threshold__gt=0, divergence_threshold__lte=100, minimum_jurors__gte=1), name='m5_campaign_ranges')]


class EvaluationCriterion(ValidatedModel):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='evaluation_criteria')
    name = models.CharField(max_length=150)
    weight = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(100)])
    max_score = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'pk']
        constraints = [models.UniqueConstraint(fields=['hackathon', 'name'], name='m5_unique_criterion'), models.CheckConstraint(condition=models.Q(weight__gt=0, weight__lte=100, max_score__gt=0), name='m5_criterion_ranges')]

    def clean(self):
        if self.pk:
            previous = EvaluationCriterion.objects.get(pk=self.pk)
            if previous.hackathon_id != self.hackathon_id:
                raise ValidationError('Le hackathon ne peut pas changer.')
        if Evaluation.objects.filter(assignment__hackathon_id=self.hackathon_id).exists():
            raise ValidationError('La grille est figée dès le premier brouillon d’évaluation.')

    def delete(self, *args, **kwargs):
        self.clean()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.name


class JuryAssignment(ValidatedModel):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='jury_assignments')
    submission = models.ForeignKey('projects.Submission', on_delete=models.PROTECT, related_name='jury_assignments')
    juror = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='jury_assignments')
    active = models.BooleanField(default=True)
    conflict_reason = models.TextField(blank=True, max_length=2000)
    conflict_resolved = models.BooleanField(default=False)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['submission', 'juror'], name='m5_unique_assignment')]

    def clean(self):
        from accounts.models import RoleAssignment, Role, AssignmentStatus
        if not self.submission_id or not self.juror_id or not self.hackathon_id:
            return
        if self.pk:
            old = JuryAssignment.objects.get(pk=self.pk)
            if (old.hackathon_id, old.submission_id, old.juror_id) != (self.hackathon_id, self.submission_id, self.juror_id):
                raise ValidationError('Retirez cette affectation et créez-en une nouvelle.')
            if not self.active and Evaluation.objects.filter(assignment_id=self.pk, status='VALIDATED').exists():
                raise ValidationError('Une affectation validée doit être conservée.')
        if not self.active:
            return
        s = self.submission
        if s.project.team.hackathon_id != self.hackathon_id or s.status != 'OFFICIAL' or s.project.official_submission_id != s.pk:
            raise ValidationError('Seule la version officielle actuelle de ce hackathon est admissible.')
        if not RoleAssignment.objects.filter(user_id=self.juror_id, user__is_active=True, hackathon_id=self.hackathon_id, role=Role.JURY, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError('Un rôle juré actif dans ce hackathon est requis.')
        if RoleAssignment.objects.filter(user_id=self.juror_id, hackathon_id=self.hackathon_id, role=Role.PARTICIPANT, status=AssignmentStatus.ACTIVE).exists():
            raise ValidationError('Un participant ne peut pas être juré.')
        if s.project.team.memberships.filter(registration__user_id=self.juror_id, ended_at__isnull=True).exists() or s.project.team.captain.user_id == self.juror_id:
            raise ValidationError('Conflit d’intérêts : membre de l’équipe.')

    @property
    def blocked(self):
        return bool(self.conflict_reason and not self.conflict_resolved)


class Evaluation(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Brouillon'
        VALIDATED = 'VALIDATED', 'Validée'

    assignment = models.OneToOneField(JuryAssignment, on_delete=models.PROTECT, related_name='evaluation')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    comment = models.TextField(blank=True, max_length=10000)
    total = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.pk:
            old = Evaluation.objects.get(pk=self.pk)
            if old.status == self.Status.VALIDATED or old.assignment_id != self.assignment_id:
                raise ValidationError('Une évaluation validée est définitivement verrouillée.')
        if self.status == self.Status.VALIDATED:
            from .scoring import evaluation_total
            if not self.pk or self.total != evaluation_total(self) or not self.validated_at:
                raise ValidationError('Validation complète des notes requise.')

    def delete(self, *args, **kwargs):
        if self.status == self.Status.VALIDATED:
            raise ValidationError('Évaluation verrouillée.')
        return super().delete(*args, **kwargs)


class CriterionScore(ValidatedModel):
    evaluation = models.ForeignKey(Evaluation, on_delete=models.PROTECT, related_name='scores')
    criterion = models.ForeignKey(EvaluationCriterion, on_delete=models.PROTECT)
    score = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['evaluation', 'criterion'], name='m5_unique_score'), models.CheckConstraint(condition=models.Q(score__gte=0), name='m5_nonnegative_score')]

    def clean(self):
        if not self.evaluation_id or not self.criterion_id:
            return
        if Evaluation.objects.filter(pk=self.evaluation_id, status='VALIDATED').exists() or (self.pk and CriterionScore.objects.filter(pk=self.pk, evaluation__status='VALIDATED').exists()):
            raise ValidationError('Évaluation verrouillée.')
        if self.criterion.hackathon_id != self.evaluation.assignment.hackathon_id:
            raise ValidationError('Critère d’un autre hackathon.')
        if self.score is not None and self.score > self.criterion.max_score:
            raise ValidationError('La note dépasse le maximum.')

    def delete(self, *args, **kwargs):
        self.clean()
        return super().delete(*args, **kwargs)


class ReviewHistory(ValidatedModel):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT)
    submission = models.ForeignKey('projects.Submission', on_delete=models.PROTECT)
    assignment = models.ForeignKey(JuryAssignment, on_delete=models.PROTECT, null=True, blank=True)
    kind = models.CharField(max_length=16, choices=[('DIVERGENCE', 'Divergence'), ('CONFLICT', 'Conflit')])
    fingerprint = models.CharField(max_length=64, blank=True)
    reason = models.TextField(max_length=2000)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class ResultPublication(ValidatedModel):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='result_publications')
    version = models.PositiveIntegerField()
    ranking = models.JSONField()
    fingerprint = models.CharField(max_length=64)
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    validated_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['hackathon', 'version'], name='m5_unique_publication_version')]

    def clean(self):
        if self.pk:
            old = ResultPublication.objects.get(pk=self.pk)
            if old.published_at or any(getattr(old, f) != getattr(self, f) for f in ('hackathon_id', 'version', 'ranking', 'fingerprint', 'validated_by_id', 'validated_at')):
                raise ValidationError('Le classement validé est immuable.')

    def delete(self, *args, **kwargs):
        raise ValidationError('L’historique des classements est conservé.')


class Prize(ValidatedModel):
    hackathon = models.ForeignKey('hackathons.Hackathon', on_delete=models.PROTECT, related_name='prizes')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, max_length=3000)
    sponsorship = models.ForeignKey('hackathons.Sponsorship', on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['hackathon', 'name'], name='m5_unique_prize')]

    def clean(self):
        if self.sponsorship_id and (self.sponsorship.hackathon_id != self.hackathon_id or self.sponsorship.status != 'CONFIRMED'):
            raise ValidationError('Choisissez un partenariat confirmé de ce hackathon.')
        if self.pk and Award.objects.filter(prize=self).exists():
            raise ValidationError('Un prix attribué est figé.')

    def __str__(self):
        return self.name


class Award(ValidatedModel):
    prize = models.OneToOneField(Prize, on_delete=models.PROTECT, related_name='award')
    submission = models.ForeignKey('projects.Submission', on_delete=models.PROTECT, related_name='awards')
    publication = models.ForeignKey(ResultPublication, on_delete=models.PROTECT, related_name='awards')
    awarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    awarded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.pk:
            raise ValidationError('Une attribution est définitive.')
        if not all((self.prize_id, self.submission_id, self.publication_id)):
            return
        if self.prize.hackathon_id != self.publication.hackathon_id or not self.publication.published_at or self.submission_id not in [r['submission_id'] for r in self.publication.ranking]:
            raise ValidationError('Le gagnant doit appartenir à un classement publié de ce hackathon.')

    def delete(self, *args, **kwargs):
        raise ValidationError('Une attribution définitive est conservée.')
