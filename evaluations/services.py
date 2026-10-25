"""Serialized M5 writes: actor then Hackathon, matching M2/M3 lock order.
No AI operation can write scores. Ranking snapshots contain public fields only.
"""
import hashlib
import json
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from accounts.models import User, Role, RoleAssignment, AssignmentStatus
from accounts.permissions import require_organizer, has_role
from hackathons.models import Hackathon
from projects.models import Submission
from .models import (EvaluationCampaign, EvaluationCriterion, JuryAssignment, Evaluation,
                     CriterionScore, ReviewHistory, ResultPublication, Prize, Award)
from .scoring import evaluation_total, mean_score


def official_submissions(event):
    return Submission.objects.filter(project__team__hackathon=event, status='OFFICIAL', project__official_submission_id=F('pk')).select_related('project__team', 'project__challenge')


def jurors(event):
    return User.objects.filter(is_active=True, role_assignments__hackathon=event, role_assignments__role=Role.JURY, role_assignments__status=AssignmentStatus.ACTIVE).distinct()


def _lock(actor, event, organizer=True):
    actor = User.objects.select_for_update(no_key=True).filter(pk=actor.pk, is_active=True).first()
    if not actor:
        raise PermissionDenied
    event = Hackathon.objects.select_for_update().get(pk=event.pk)
    if organizer:
        require_organizer(actor, event)
    elif event.status == 'ARCHIVED':
        raise ValidationError('Édition archivée : consultation uniquement.')
    return event


def campaign(event):
    return EvaluationCampaign.objects.get_or_create(hackathon=event)[0]


def require_assignment(actor, assignment):
    if not actor.is_active or actor.pk != assignment.juror_id or not assignment.active or not has_role(actor, assignment.hackathon, Role.JURY):
        raise PermissionDenied
    assignment.full_clean()
    if assignment.blocked:
        raise ValidationError('Conflit d’intérêts non résolu : accès suspendu.')


@transaction.atomic
def configure_rubric(*, actor, event, rows, threshold, minimum_jurors, validate=False):
    event = _lock(actor, event)
    if Evaluation.objects.filter(assignment__hackathon=event).exists():
        raise ValidationError('La grille est figée dès le premier brouillon.')
    c = campaign(event)
    ids = set(event.evaluation_criteria.values_list('pk', flat=True))
    kept, names, total = set(), set(), Decimal(0)
    for row in rows:
        pk = row.get('id')
        if pk and pk not in ids:
            raise ValidationError('Critère d’un autre hackathon.')
        if row.get('DELETE'):
            continue
        if row['name'] in names:
            raise ValidationError('Chaque critère doit avoir un nom unique.')
        names.add(row['name'])
        obj = EvaluationCriterion.objects.get(pk=pk) if pk else EvaluationCriterion(hackathon=event)
        for field in ('name', 'weight', 'max_score', 'display_order'):
            setattr(obj, field, row[field])
        obj.save()
        kept.add(obj.pk)
        total += obj.weight
    if validate and (not kept or total != 100):
        raise ValidationError('La somme des poids doit être égale à 100 %.')
    event.evaluation_criteria.filter(pk__in=ids - kept).delete()
    c.rubric_validated = validate
    c.divergence_threshold, c.minimum_jurors = threshold, minimum_jurors
    c.save()
    return c


@transaction.atomic
def assign(*, actor, event, submission, juror):
    event = _lock(actor, event)
    obj, created = JuryAssignment.objects.get_or_create(hackathon=event, submission=submission, juror=juror, defaults={'assigned_by': actor})
    obj.active = True
    obj.save()
    return obj


@transaction.atomic
def change_assignment(*, actor, assignment, action, reason=''):
    event = _lock(actor, assignment.hackathon, organizer=action != 'report')
    obj = JuryAssignment.objects.get(pk=assignment.pk, hackathon=event)
    if action == 'report':
        if actor.pk != obj.juror_id or not has_role(actor, event, Role.JURY) or not obj.active:
            raise PermissionDenied
        if not reason.strip():
            raise ValidationError('Justification requise.')
        obj.conflict_reason, obj.conflict_resolved = reason.strip(), False
    elif action == 'resolve':
        if not obj.conflict_reason or not reason.strip():
            raise ValidationError('Une justification de résolution est requise.')
        obj.conflict_resolved = True
    elif action == 'remove':
        if Evaluation.objects.filter(assignment=obj, status='VALIDATED').exists():
            raise ValidationError('Une affectation évaluée définitivement doit être conservée.')
        obj.active = False
    else:
        raise ValidationError('Action inconnue.')
    obj.save()
    ReviewHistory.objects.create(hackathon=event, submission=obj.submission, assignment=obj, kind='CONFLICT', reason=f'{action}: {reason.strip()}', actor=actor)
    return obj


@transaction.atomic
def save_evaluation(*, actor, assignment, scores, comment='', finalize=False):
    event = _lock(actor, assignment.hackathon, organizer=False)
    assignment = JuryAssignment.objects.select_related('hackathon', 'submission__project__team__captain').get(pk=assignment.pk)
    require_assignment(actor, assignment)
    c = campaign(event)
    if not c.rubric_validated:
        raise ValidationError('L’organisateur doit valider la grille avant la notation.')
    evaluation, _ = Evaluation.objects.get_or_create(assignment=assignment)
    if evaluation.status == 'VALIDATED':
        raise ValidationError('Cette évaluation est définitivement verrouillée.')
    criteria = {c.pk: c for c in event.evaluation_criteria.all()}
    if not set(scores).issubset(criteria):
        raise ValidationError('Critère d’un autre hackathon.')
    for pk, value in scores.items():
        if value is None:
            evaluation.scores.filter(criterion_id=pk).delete()
            continue
        obj, _ = CriterionScore.objects.get_or_create(evaluation=evaluation, criterion=criteria[pk], defaults={'score': value})
        obj.score = value
        obj.save()
    evaluation.comment = comment
    try:
        evaluation.total = evaluation_total(evaluation)
    except ValidationError:
        if finalize:
            raise
        evaluation.total = None
    if finalize:
        evaluation.status = Evaluation.Status.VALIDATED
        evaluation.validated_at = timezone.now()
    evaluation.save()
    return evaluation


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def ranking(event):
    c = EvaluationCampaign.objects.filter(hackathon=event).first()
    minimum = c.minimum_jurors if c else 1
    threshold = c.divergence_threshold if c else Decimal(25)
    rows = []
    for sub in official_submissions(event):
        assignments = list(sub.jury_assignments.filter(active=True).select_related('juror', 'evaluation', 'hackathon').order_by('pk'))
        totals, evidence, invalid = [], [], False
        for a in assignments:
            try:
                a.full_clean()
            except ValidationError:
                invalid = True
            ev = getattr(a, 'evaluation', None)
            evidence.append((a.pk, a.juror_id, a.blocked, ev.pk if ev else None, str(ev.total) if ev else None, ev.status if ev else None))
            if ev and ev.status == 'VALIDATED':
                totals.append(ev.total)
        spread = max(totals) - min(totals) if len(totals) > 1 else Decimal(0)
        review_key = fingerprint({'evidence': evidence, 'threshold': threshold})
        divergent = spread >= threshold
        resolved = divergent and ReviewHistory.objects.filter(hackathon=event, submission=sub, kind='DIVERGENCE', fingerprint=review_key).exists()
        complete = bool(len(assignments) >= minimum and len(totals) == len(assignments) and not invalid and not any(a.blocked for a in assignments))
        snap = sub.snapshot
        rows.append({'submission_id': sub.pk, 'project_id': sub.project_id, 'version': sub.version,
                     'project': snap.get('title', sub.project.title), 'team': snap.get('team', sub.project.team.name),
                     'challenge': snap.get('challenge', sub.project.challenge.title),
                     'score': str(mean_score(totals)) if totals else None,
                     'jurors': len(totals), 'assigned': len(assignments), 'complete': complete,
                     'spread': str(spread), 'divergent': divergent, 'resolved': bool(resolved),
                     'review_key': review_key, 'evidence': evidence})
    rows.sort(key=lambda r: (r['score'] is None, -Decimal(r['score'] or '0'), r['project_id']))
    last, rank = object(), 0
    for position, row in enumerate(rows, 1):
        if row['score'] != last:
            rank = position
        row['rank'] = rank if row['score'] is not None else None
        last = row['score']
    return rows


@transaction.atomic
def resolve_divergence(*, actor, event, submission, reason):
    event = _lock(actor, event)
    row = next((r for r in ranking(event) if r['submission_id'] == submission.pk), None)
    if not row or not row['divergent'] or not reason.strip():
        raise ValidationError('Une divergence et une justification sont requises.')
    return ReviewHistory.objects.create(hackathon=event, submission=submission, kind='DIVERGENCE', fingerprint=row['review_key'], reason=reason.strip(), actor=actor)


def publication_ready(event, rows):
    c = EvaluationCampaign.objects.filter(hackathon=event, rubric_validated=True).first()
    if not c or not rows or any(not r['complete'] or (r['divergent'] and not r['resolved']) for r in rows):
        raise ValidationError('Publication bloquée : grille, affectations, notes ou divergences incomplètes.')
    if timezone.now() < event.submission_deadline:
        raise ValidationError('La date limite de soumission doit être dépassée.')
    # M3 can reopen a project. Do not silently drop it from a previously evaluated cohort.
    if JuryAssignment.objects.filter(hackathon=event, active=True).exclude(submission_id__in=[r['submission_id'] for r in rows]).exists():
        raise ValidationError('Des affectations concernent une ancienne version : vérifiez les soumissions M3.')


def public_rows(rows):
    fields = ('rank', 'submission_id', 'project_id', 'version', 'project', 'team', 'challenge', 'score', 'jurors', 'complete')
    return [{k: row[k] for k in fields} for row in rows]


@transaction.atomic
def validate_ranking(*, actor, event):
    event = _lock(actor, event)
    rows = ranking(event)
    publication_ready(event, rows)
    key = fingerprint(rows)
    previous = event.result_publications.filter(fingerprint=key).first()
    if previous:
        return previous
    version = (event.result_publications.aggregate(value=Max('version'))['value'] or 0) + 1
    return ResultPublication.objects.create(hackathon=event, version=version, ranking=public_rows(rows), fingerprint=key, validated_by=actor)


@transaction.atomic
def publish(*, actor, publication):
    event = _lock(actor, publication.hackathon)
    publication = ResultPublication.objects.get(pk=publication.pk, hackathon=event)
    if publication.published_at:
        return publication
    rows = ranking(event)
    publication_ready(event, rows)
    if fingerprint(rows) != publication.fingerprint:
        raise ValidationError('Les données ont changé. Validez un nouveau classement.')
    latest = event.result_publications.filter(published_at__isnull=False).first()
    if latest and latest.version > publication.version:
        raise ValidationError('Une version plus récente est déjà publiée.')
    publication.published_by, publication.published_at = actor, timezone.now()
    publication.save()
    return publication


@transaction.atomic
def save_prize(*, actor, event, data, prize=None):
    event = _lock(actor, event)
    obj = Prize.objects.get(pk=prize.pk, hackathon=event) if prize else Prize(hackathon=event)
    for key in ('name', 'description', 'sponsorship'):
        setattr(obj, key, data[key])
    obj.save()
    return obj


@transaction.atomic
def award(*, actor, prize, submission):
    event = _lock(actor, prize.hackathon)
    publication = event.result_publications.filter(published_at__isnull=False).first()
    if not publication:
        raise ValidationError('Publiez les résultats avant l’attribution.')
    existing = Award.objects.filter(prize=prize).first()
    if existing:
        if existing.submission_id == submission.pk:
            return existing
        raise ValidationError('Ce prix est déjà attribué.')
    return Award.objects.create(prize=prize, submission=submission, publication=publication, awarded_by=actor)


def copilot_input(*, actor, event):
    require_organizer(actor, event, mutable=False)
    return {'schema_version': 1, 'hackathon_id': event.pk, 'ranking': ranking(event), 'policy': 'Analyse consultative uniquement ; aucune modification automatique des notes.'}
