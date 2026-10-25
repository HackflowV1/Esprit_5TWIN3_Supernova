import hashlib
import json
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def private_storage():
    # Deliberately outside MEDIA_ROOT: even DEBUG must not expose private files.
    return FileSystemStorage(location=settings.PROJECT_FILES_ROOT, base_url=None)


def deliverable_path(instance, filename):
    return f'{instance.submission_id}/{uuid4().hex}{Path(filename).suffix.lower()}'


class Project(models.Model):
    class Status(models.TextChoices):
        IDEA = 'IDEA', _('Idée')
        BUILDING = 'BUILDING', _('En développement')
        READY = 'READY', _('Prêt à soumettre')

    team = models.OneToOneField('teams.Team', on_delete=models.PROTECT, related_name='project')
    challenge = models.ForeignKey('hackathons.Challenge', on_delete=models.PROTECT, related_name='projects')
    title = models.CharField(_('Titre du projet'), max_length=200)
    problem = models.TextField(_('Problème'), max_length=10000)
    solution = models.TextField(_('Solution'), max_length=10000)
    stack = models.CharField(_('Technologies'), max_length=500)
    pitch = models.TextField(_('Pitch'), max_length=5000, blank=True)
    status = models.CharField(_('État du projet'), max_length=12, choices=Status.choices, default=Status.IDEA)
    official_submission = models.ForeignKey('Submission', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    public_requested = models.BooleanField(default=False)
    published = models.BooleanField(default=False)
    exception_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title', 'pk']

    def clean(self):
        if self.team_id and self.challenge_id and self.team.hackathon_id != self.challenge.track.hackathon_id:
            raise ValidationError(_('L’équipe et le challenge doivent appartenir au même hackathon.'))
        if self.official_submission_id and (self.official_submission.project_id != self.pk or self.official_submission.status != 'OFFICIAL'):
            raise ValidationError(_('La version officielle doit être une soumission officielle de ce projet.'))
        if self.published and (not self.official_submission_id or not self.public_requested):
            raise ValidationError(_('Une version officielle et l’accord de l’équipe sont requis.'))

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('projects:detail', args=[self.pk])

    @property
    def progress(self):
        values = list(self.milestones.values_list('progress', flat=True))
        return round(sum(values) / len(values)) if values else 0


class Milestone(models.Model):
    class State(models.TextChoices):
        TODO = 'TODO', _('À faire')
        DOING = 'DOING', _('En cours')
        DONE = 'DONE', _('Terminé')

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='milestones')
    title = models.CharField(_('Étape'), max_length=200)
    due_at = models.DateTimeField(_('Échéance'))
    state = models.CharField(_('État'), max_length=8, choices=State.choices, default=State.TODO)
    progress = models.PositiveSmallIntegerField(_('Progression (%)'), default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        ordering = ['due_at', 'pk']
        constraints = [models.CheckConstraint(condition=Q(progress__lte=100), name='m3_progress_range')]

    def clean(self):
        # Progress is the single input; the kanban state follows it.
        if self.progress is not None:
            self.state = self.State.TODO if self.progress == 0 else self.State.DONE if self.progress == 100 else self.State.DOING


class Submission(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Brouillon')
        OFFICIAL = 'OFFICIAL', _('Officielle — figée')
        DISCARDED = 'DISCARDED', _('Brouillon supprimé')

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='submissions')
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    snapshot = models.JSONField(default=dict, blank=True)
    requirements_confirmed = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['project', 'version'], name='m3_unique_project_version'), models.CheckConstraint(condition=Q(version__gte=1), name='m3_positive_version')]

    def __str__(self):
        return f'{self.project} · v{self.version}'

    def save(self, *args, **kwargs):
        if self.pk and Submission.objects.filter(pk=self.pk, status=self.Status.OFFICIAL).exists():
            raise ValidationError(_('Cette version est figée. Créez une nouvelle version.'))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.Status.OFFICIAL:
            raise ValidationError(_('Cette version est figée. Créez une nouvelle version.'))
        return super().delete(*args, **kwargs)


class Deliverable(models.Model):
    class Kind(models.TextChoices):
        REPOSITORY = 'REPOSITORY', _('Dépôt de code')
        DEMO = 'DEMO', _('Démo')
        SLIDES = 'SLIDES', _('Présentation')
        VIDEO = 'VIDEO', _('Vidéo')

    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name='deliverables')
    kind = models.CharField(_('Type'), max_length=12, choices=Kind.choices)
    url = models.URLField(_('Lien HTTPS'), max_length=1000, blank=True)
    file = models.FileField(_('Fichier'), storage=private_storage, upload_to=deliverable_path, blank=True)
    commit = models.CharField(_('Commit Git complet'), max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['submission', 'kind'], name='m3_one_deliverable_kind')]

    def clean(self):
        if bool(self.url) == bool(self.file):
            raise ValidationError(_('Fournissez un lien ou un fichier, exclusivement.'))
        if self.kind == self.Kind.REPOSITORY and (not self.url or not self.commit):
            raise ValidationError(_('Un dépôt requiert un lien et le commit Git évalué.'))

    def _require_draft(self):
        ids = {self.submission_id}
        if self.pk:
            ids.update(Deliverable.objects.filter(pk=self.pk).values_list('submission_id', flat=True))
        if Submission.objects.filter(pk__in=ids).exclude(status=Submission.Status.DRAFT).exists():
            raise ValidationError(_('Cette version est figée. Créez une nouvelle version.'))

    def save(self, *args, **kwargs):
        self._require_draft()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._require_draft()
        return super().delete(*args, **kwargs)


class ProjectActivity(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='activities')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=40)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    @property
    def label(self):
        return {
            'CREATE_PROJECT': _('Projet créé'), 'UPDATE_PROJECT': _('Fiche du projet modifiée'),
            'SAVE_MILESTONE': _('Étape enregistrée'), 'DELETE_MILESTONE': _('Étape supprimée'),
            'CREATE_VERSION': _('Version créée'), 'SAVE_DELIVERABLE': _('Livrable enregistré'),
            'DELETE_DELIVERABLE': _('Livrable retiré'), 'SUBMIT': _('Version officialisée'),
            'REOPEN': _('Dépôt réouvert par dérogation'), 'PUBLICATION': _('Visibilité modifiée'),
            'DISCARD_VERSION': _('Brouillon supprimé'), 'RESTORE_VERSION': _('Brouillon restauré'),
            'MOVE_MILESTONE': _('Étape déplacée'),
            'AI_ANALYSIS': _('Analyse IA du projet réalisée'),
            'APPLY_AI_PITCH': _('Pitch IA appliqué au projet'),
        }.get(self.action, _('Activité du projet'))


def compute_project_fingerprint(target):
    """Compute deterministic SHA-256 fingerprint for project content analyzed by AI."""
    if hasattr(target, 'problem'):  # Project model instance
        challenge_id = target.challenge_id
        challenge_obj = getattr(target, 'challenge', None)
        requirements = (challenge_obj.deliverables or '').strip() if challenge_obj else ''
        payload = {
            'title': (target.title or '').strip(),
            'problem': (target.problem or '').strip(),
            'solution': (target.solution or '').strip(),
            'stack': (target.stack or '').strip(),
            'pitch': (target.pitch or '').strip(),
            'challenge_id': challenge_id,
            'requirements': requirements,
        }
    elif isinstance(target, dict):
        payload = {
            'title': str(target.get('title') or '').strip(),
            'problem': str(target.get('problem') or '').strip(),
            'solution': str(target.get('solution') or '').strip(),
            'stack': str(target.get('stack') or '').strip(),
            'pitch': str(target.get('pitch') or '').strip(),
            'challenge_id': target.get('challenge_id'),
            'requirements': str(target.get('requirements') or '').strip(),
        }
    else:
        payload = {}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


class ProjectAIAnalysis(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='ai_analyses')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    provider = models.CharField(max_length=50, default='gemini')
    model = models.CharField(max_length=100)
    summary = models.TextField(_('Résumé du projet'), blank=True)
    suggestions = models.JSONField(_('Suggestions d’amélioration'), default=list, blank=True)
    questions = models.JSONField(_('Questions sur les points flous'), default=list, blank=True)
    pitch = models.TextField(_('Proposition de pitch (60s)'), blank=True)
    snapshot = models.JSONField(_('Instantané analysé'), default=dict, blank=True)
    fingerprint = models.CharField(_('Empreinte du contenu'), max_length=64, db_index=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.project.title} · IA ({self.created_at:%Y-%m-%d %H:%M})'

    def is_outdated(self, current_project=None):
        target = current_project or self.project
        return self.fingerprint != compute_project_fingerprint(target)

