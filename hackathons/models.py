from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, F
from django.urls import reverse
from django.utils import timezone
from core.validators import validate_image_size


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Hackathon(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Brouillon'
        PUBLISHED = 'PUBLISHED', 'Publié'
        ONGOING = 'ONGOING', 'En cours'
        FINISHED = 'FINISHED', 'Terminé'
        ARCHIVED = 'ARCHIVED', 'Archivé'

    class Format(models.TextChoices):
        ONSITE = 'ONSITE', 'Présentiel'
        ONLINE = 'ONLINE', 'En ligne'
        HYBRID = 'HYBRID', 'Hybride'

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=220)
    description = models.TextField()
    rules = models.TextField()
    participation_conditions = models.TextField(blank=True)
    image = models.ImageField(upload_to='hackathons/', blank=True, validators=[validate_image_size])
    location = models.CharField(max_length=200, blank=True)
    format = models.CharField(max_length=10, choices=Format.choices, default=Format.ONSITE)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    registration_open = models.DateTimeField()
    registration_close = models.DateTimeField()
    submission_deadline = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=100, validators=[MinValueValidator(1)])
    min_team_size = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    max_team_size = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1)])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_hackathons')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archive_metrics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-start_date']
        constraints = [
            models.CheckConstraint(condition=Q(start_date__lt=F('end_date')), name='hackathon_dates_order'),
            models.CheckConstraint(condition=Q(registration_open__lt=F('registration_close')), name='registration_dates_order'),
            models.CheckConstraint(condition=Q(registration_close__lte=F('end_date')), name='registration_before_end'),
            models.CheckConstraint(condition=Q(submission_deadline__gte=F('start_date'), submission_deadline__lte=F('end_date')), name='submission_within_event'),
            models.CheckConstraint(condition=Q(capacity__gte=1, min_team_size__gte=1, max_team_size__gte=F('min_team_size')) & Q(capacity__gte=F('max_team_size')), name='event_capacity_sizes'),
        ]

    def clean(self):
        super().clean()
        if self.pk and Hackathon.objects.filter(pk=self.pk, status=self.Status.ARCHIVED).exists():
            raise ValidationError('Édition archivée : modification interdite.')
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError('Le début doit précéder la fin.')
        if self.registration_open and self.registration_close and self.registration_open >= self.registration_close:
            raise ValidationError('Période d’inscription invalide.')
        if self.registration_close and self.end_date and self.registration_close > self.end_date:
            raise ValidationError('Les inscriptions doivent finir avant la fin de l’événement.')
        if self.submission_deadline and self.start_date and self.end_date and not self.start_date <= self.submission_deadline <= self.end_date:
            raise ValidationError('Deadline de soumission hors événement.')
        if self.min_team_size and self.max_team_size and self.capacity and not 1 <= self.min_team_size <= self.max_team_size <= self.capacity:
            raise ValidationError('Tailles d’équipe ou capacité incohérentes.')
        if self.pk and self.status != self.Status.ARCHIVED:
            for phase in self.phases.all():
                phase.hackathon = self
                phase.clean()

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('hackathons:detail', kwargs={'slug': self.slug})


class EventResource(ValidatedModel):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        event = self.get_hackathon()
        if event and event.status == Hackathon.Status.ARCHIVED:
            raise ValidationError('Édition archivée : modification interdite.')


class Track(EventResource):
    hackathon = models.ForeignKey(Hackathon, on_delete=models.PROTECT, related_name='tracks')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['hackathon', 'name'], name='unique_event_track')]

    def get_hackathon(self):
        return self.hackathon if self.hackathon_id else None

    def __str__(self):
        return self.name


class SponsorOrganization(ValidatedModel):
    name = models.CharField(max_length=200, unique=True)
    logo = models.ImageField(upload_to='sponsors/', blank=True, validators=[validate_image_size])
    sector = models.CharField(max_length=150, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Sponsorship(EventResource):
    class Status(models.TextChoices):
        PROPOSED = 'PROPOSED', 'Proposé'
        CONFIRMED = 'CONFIRMED', 'Confirmé'
        CANCELLED = 'CANCELLED', 'Annulé'

    organization = models.ForeignKey(SponsorOrganization, on_delete=models.PROTECT, related_name='sponsorships')
    hackathon = models.ForeignKey(Hackathon, on_delete=models.PROTECT, related_name='sponsorships')
    contribution_type = models.CharField(max_length=150)
    estimated_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default='TND')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    prize_information = models.TextField(blank=True, help_text='Information pour M5 ; aucune attribution de prix dans M1.')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['organization', 'hackathon'], name='unique_event_sponsor'),
            models.CheckConstraint(condition=Q(estimated_value__isnull=True) | Q(estimated_value__gte=0), name='nonnegative_sponsorship'),
        ]

    def get_hackathon(self):
        return self.hackathon if self.hackathon_id else None

    def clean(self):
        super().clean()
        if self.pk and self.status != self.Status.CONFIRMED and self.challenges.filter(status__in=['APPROVED', 'PUBLISHED']).exists():
            raise ValidationError({'status': 'Retirez les challenges validés avant de désactiver le partenariat.'})
        if self.pk and Sponsorship.objects.filter(pk=self.pk).exclude(organization_id=self.organization_id).exists():
            raise ValidationError({'organization': 'L’organisation d’un partenariat existant ne peut pas changer.'})

    def save(self, *args, **kwargs):
        if self.status == self.Status.CONFIRMED and self.confirmed_at is None:
            self.confirmed_at = timezone.now()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.organization} / {self.hackathon}'


class Challenge(EventResource):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Brouillon'
        PROPOSED = 'PROPOSED', 'À valider'
        APPROVED = 'APPROVED', 'Validé'
        PUBLISHED = 'PUBLISHED', 'Publié'
        WITHDRAWN = 'WITHDRAWN', 'Retiré'

    track = models.ForeignKey(Track, on_delete=models.PROTECT, related_name='challenges')
    title = models.CharField(max_length=200)
    problem = models.TextField()
    objectives = models.TextField()
    deliverables = models.TextField()
    participation_conditions = models.TextField(blank=True)
    sponsorship = models.ForeignKey(Sponsorship, on_delete=models.PROTECT, null=True, blank=True, related_name='challenges')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='proposed_challenges')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='approved_challenges')
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_hackathon(self):
        return self.track.hackathon if self.track_id else None

    def clean(self):
        super().clean()
        if self.track_id and self.sponsorship_id and self.track.hackathon_id != self.sponsorship.hackathon_id:
            raise ValidationError('Le partenariat doit appartenir au hackathon du track.')
        if self.status in (self.Status.APPROVED, self.Status.PUBLISHED):
            if not all(str(x).strip() for x in (self.title, self.problem, self.objectives, self.deliverables)):
                raise ValidationError('Les consignes et livrables doivent être complets.')
            if not self.approved_by_id or not self.approved_at:
                raise ValidationError('Validation organisateur requise.')
            if self.sponsorship_id and self.sponsorship.status != Sponsorship.Status.CONFIRMED:
                raise ValidationError('Partenariat confirmé requis.')

    def __str__(self):
        return self.title


class EventPhase(EventResource):
    class Kind(models.TextChoices):
        REGISTRATION = 'REGISTRATION', 'Inscriptions'
        TEAM_FORMATION = 'TEAM_FORMATION', 'Constitution des équipes'
        DEVELOPMENT = 'DEVELOPMENT', 'Développement'
        SUBMISSION = 'SUBMISSION', 'Soumissions'
        EVALUATION = 'EVALUATION', 'Évaluations'
        RESULTS = 'RESULTS', 'Résultats'

    hackathon = models.ForeignKey(Hackathon, on_delete=models.PROTECT, related_name='phases')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    start = models.DateTimeField()
    end = models.DateTimeField()

    class Meta:
        ordering = ['start']
        constraints = [
            models.UniqueConstraint(fields=['hackathon', 'kind'], name='unique_event_phase_kind'),
            models.CheckConstraint(condition=Q(start__lt=F('end')), name='phase_dates_order'),
        ]

    def get_hackathon(self):
        return self.hackathon if self.hackathon_id else None

    def clean(self):
        super().clean()
        if not (self.start and self.end and self.hackathon_id):
            return
        if self.start >= self.end:
            raise ValidationError('Le début de phase doit précéder sa fin.')
        h = self.hackathon
        if not all((h.start_date, h.end_date, h.registration_open, h.registration_close, h.submission_deadline)):
            return
        earliest = h.registration_open if self.kind in (self.Kind.REGISTRATION, self.Kind.TEAM_FORMATION) else h.start_date
        if self.start < earliest or self.end > h.end_date:
            raise ValidationError('Phase hors calendrier de l’événement.')
        if self.kind == self.Kind.REGISTRATION and (self.start != h.registration_open or self.end != h.registration_close):
            raise ValidationError('La phase inscriptions doit correspondre aux dates d’inscription.')
        if self.kind == self.Kind.SUBMISSION and self.end != h.submission_deadline:
            raise ValidationError('La fin des soumissions doit correspondre à la deadline.')
        if self.kind == self.Kind.EVALUATION and self.start < h.submission_deadline:
            raise ValidationError('L’évaluation doit commencer après la deadline de soumission.')
        # Registration/formation and development/submission intentionally may overlap.
        forbidden = {
            self.Kind.EVALUATION: [self.Kind.DEVELOPMENT, self.Kind.SUBMISSION, self.Kind.RESULTS],
            self.Kind.RESULTS: [self.Kind.DEVELOPMENT, self.Kind.SUBMISSION, self.Kind.EVALUATION],
            self.Kind.DEVELOPMENT: [self.Kind.EVALUATION, self.Kind.RESULTS],
            self.Kind.SUBMISSION: [self.Kind.EVALUATION, self.Kind.RESULTS],
        }.get(self.kind, [])
        if h.phases.filter(kind__in=forbidden, start__lt=self.end, end__gt=self.start).exclude(pk=self.pk).exists():
            raise ValidationError('Chevauchement de phases incompatible.')
        if self.kind == self.Kind.RESULTS and h.phases.filter(kind=self.Kind.EVALUATION, end__gt=self.start).exclude(pk=self.pk).exists():
            raise ValidationError('Les résultats doivent suivre l’évaluation.')
        if self.kind == self.Kind.EVALUATION and h.phases.filter(kind=self.Kind.RESULTS, start__lt=self.end).exclude(pk=self.pk).exists():
            raise ValidationError('L’évaluation doit précéder les résultats.')

    @property
    def state(self):
        now = timezone.now()
        return 'À venir' if now < self.start else ('En cours' if now < self.end else 'Terminée')

    def __str__(self):
        return self.get_kind_display()


class EventHistory(models.Model):
    hackathon = models.ForeignKey(Hackathon, on_delete=models.PROTECT, related_name='history')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100)
    target = models.CharField(max_length=200)
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp', '-pk']
