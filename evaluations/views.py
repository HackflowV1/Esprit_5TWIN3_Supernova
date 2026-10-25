from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from accounts.models import Role, AssignmentStatus
from accounts.permissions import require_organizer, can_manage
from hackathons.models import Hackathon
from projects.models import Deliverable, Submission
from .models import EvaluationCampaign, JuryAssignment, Evaluation, ResultPublication, Prize, ReviewHistory
from .forms import (CriterionFormSet, CampaignForm, AssignmentForm, EvaluationForm, ReasonForm, PrizeForm, AwardForm)
from . import services


def _event(request, slug, mutable=False):
    event = get_object_or_404(Hackathon, slug=slug)
    require_organizer(request.user, event, mutable=mutable)
    return event


def _context(event, **kwargs):
    return {'event': event, 'ui_app': 'evaluations', 'private_workspace': True, **kwargs}


def _error(request, error):
    messages.error(request, ' '.join(error.messages))


@login_required
def hub(request):
    events = Hackathon.objects.filter(role_assignments__user=request.user, role_assignments__status=AssignmentStatus.ACTIVE, role_assignments__role__in=[Role.ORGANIZER, Role.JURY]).distinct()
    if request.user.is_superuser:
        events = Hackathon.objects.all()
    cards = [{'event': e, 'organizer': can_manage(request.user, e)} for e in events]
    assignments = JuryAssignment.objects.filter(juror=request.user, active=True, hackathon__role_assignments__user=request.user, hackathon__role_assignments__role=Role.JURY, hackathon__role_assignments__status='ACTIVE').select_related('hackathon', 'submission__project__team', 'evaluation').distinct()
    counts = {'pending': 0, 'draft': 0, 'validated': 0}
    items = []
    for a in assignments:
        ev = getattr(a, 'evaluation', None)
        state = 'pending' if not ev else 'validated' if ev.status == 'VALIDATED' else 'draft'
        counts[state] += 1
        items.append({'assignment': a, 'state': state, 'evaluation': ev})
    return render(request, 'evaluations/hub.html', {'cards': cards, 'items': items, 'counts': counts, 'ui_app': 'evaluations'})


@login_required
def dashboard(request, slug):
    event = _event(request, slug)
    rows = services.ranking(event)
    assignments = JuryAssignment.objects.filter(hackathon=event, active=True)
    finished = Evaluation.objects.filter(assignment__in=assignments, status='VALIDATED').count()
    total = assignments.count()
    metrics = [('Projets soumis', len(rows)), ('Jurés autorisés', services.jurors(event).count()), ('Affectations', total), ('En attente ou brouillon', total-finished), ('Évaluations terminées', finished), ('Projets sans notes', sum(r['jurors'] == 0 for r in rows)), ('Projets sans juré', sum(r['assigned'] == 0 for r in rows)), ('Divergences à vérifier', sum(r['divergent'] and not r['resolved'] for r in rows))]
    return render(request, 'evaluations/dashboard.html', _context(event, rows=rows, metrics=metrics, progress=round(finished*100/total) if total else 0))


@login_required
def rubric(request, slug):
    event = _event(request, slug)
    c = EvaluationCampaign.objects.filter(hackathon=event).first() or EvaluationCampaign(hackathon=event)
    locked = Evaluation.objects.filter(assignment__hackathon=event).exists()
    formset = CriterionFormSet(request.POST if request.method == 'POST' else None, initial=list(event.evaluation_criteria.values('id', 'name', 'weight', 'max_score', 'display_order')))
    settings_form = CampaignForm(request.POST if request.method == 'POST' else None, instance=c)
    if request.method == 'POST' and formset.is_valid() and settings_form.is_valid():
        try:
            services.configure_rubric(actor=request.user, event=event, rows=[r for r in formset.cleaned_data if r], threshold=settings_form.cleaned_data['divergence_threshold'], minimum_jurors=settings_form.cleaned_data['minimum_jurors'], validate=request.POST.get('action') == 'validate')
            messages.success(request, 'Grille enregistrée.')
            return redirect('evaluations:rubric', slug=slug)
        except ValidationError as error:
            _error(request, error)
    return render(request, 'evaluations/rubric.html', _context(event, formset=formset, form=settings_form, locked=locked, campaign=c))


@login_required
def assignments(request, slug):
    event = _event(request, slug)
    form = AssignmentForm(request.POST if request.method == 'POST' else None, event=event)
    if request.method == 'POST' and form.is_valid():
        try:
            services.assign(actor=request.user, event=event, **form.cleaned_data)
            messages.success(request, 'Affectation enregistrée.')
            return redirect('evaluations:assignments', slug=slug)
        except ValidationError as error:
            _error(request, error)
    items = JuryAssignment.objects.filter(hackathon=event).select_related('juror', 'submission__project', 'evaluation')
    rows = services.ranking(event)
    return render(request, 'evaluations/assignments.html', _context(event, form=form, assignments=items, jurors=services.jurors(event), unassigned=[r for r in rows if not r['assigned']]))


@login_required
@require_POST
def assignment_action(request, pk):
    assignment = get_object_or_404(JuryAssignment.objects.select_related('hackathon'), pk=pk)
    try:
        services.change_assignment(actor=request.user, assignment=assignment, action=request.POST.get('action'), reason=request.POST.get('reason', ''))
        messages.success(request, 'Affectation mise à jour.')
    except ValidationError as error:
        _error(request, error)
    if request.POST.get('action') == 'report':
        return redirect('evaluations:hub')
    return redirect('evaluations:assignments', slug=assignment.hackathon.slug)


@login_required
def evaluate(request, pk):
    a = get_object_or_404(JuryAssignment.objects.select_related('hackathon', 'submission__project__team__captain'), pk=pk)
    try:
        services.require_assignment(request.user, a)
    except ValidationError as error:
        _error(request, error)
        return redirect('evaluations:hub')
    ev = Evaluation.objects.filter(assignment=a).first()
    locked = bool(ev and ev.status == 'VALIDATED')
    form = EvaluationForm(request.POST if request.method == 'POST' else None, criteria=a.hackathon.evaluation_criteria.all(), evaluation=ev)
    if request.method == 'POST':
        if locked:
            raise PermissionDenied('Évaluation verrouillée.')
        if form.is_valid():
            try:
                services.save_evaluation(actor=request.user, assignment=a, scores=form.scores(), comment=form.cleaned_data['comment'], finalize=request.POST.get('action') == 'finalize')
                messages.success(request, 'Évaluation enregistrée.')
                return redirect('evaluations:evaluate', pk=pk)
            except ValidationError as error:
                form.add_error(None, error)
    return render(request, 'evaluations/evaluate.html', _context(a.hackathon, assignment=a, submission=a.submission, snapshot=a.submission.snapshot, deliverables=a.submission.deliverables.all(), evaluation=ev, form=form, locked=locked, private_workspace=False))


@login_required
def download(request, pk, deliverable_pk):
    a = get_object_or_404(JuryAssignment.objects.select_related('hackathon', 'submission__project__team__captain'), pk=pk)
    try:
        services.require_assignment(request.user, a)
    except ValidationError:
        raise PermissionDenied
    record = get_object_or_404(Deliverable, pk=deliverable_pk, submission=a.submission)
    if not record.file:
        raise Http404
    try:
        return FileResponse(record.file.open('rb'), as_attachment=True, filename=Path(record.file.name).name, content_type='application/octet-stream')
    except FileNotFoundError:
        raise Http404


@login_required
def ranking(request, slug):
    event = _event(request, slug)
    if request.method == 'POST':
        try:
            p = services.validate_ranking(actor=request.user, event=event)
            messages.success(request, f'Classement v{p.version} validé. Vous pouvez le publier.')
            return redirect('evaluations:ranking', slug=slug)
        except ValidationError as error:
            _error(request, error)
    return render(request, 'evaluations/ranking.html', _context(event, rows=services.ranking(event), publications=event.result_publications.all()))


@login_required
@require_POST
def publish(request, slug, pk):
    event = _event(request, slug, mutable=True)
    p = get_object_or_404(ResultPublication, hackathon=event, pk=pk)
    try:
        services.publish(actor=request.user, publication=p)
        messages.success(request, 'Résultats officiellement publiés.')
    except ValidationError as error:
        _error(request, error)
    return redirect('evaluations:ranking', slug=slug)


@login_required
def anomalies(request, slug):
    event = _event(request, slug)
    form = ReasonForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        sub = get_object_or_404(Submission, pk=request.POST.get('submission'), project__team__hackathon=event)
        try:
            services.resolve_divergence(actor=request.user, event=event, submission=sub, **form.cleaned_data)
            messages.success(request, 'Vérification enregistrée ; aucune note modifiée.')
            return redirect('evaluations:anomalies', slug=slug)
        except ValidationError as error:
            _error(request, error)
    return render(request, 'evaluations/anomalies.html', _context(event, rows=[r for r in services.ranking(event) if r['divergent']], history=ReviewHistory.objects.filter(hackathon=event).select_related('actor', 'submission__project', 'assignment').order_by('-created_at'), form=form))


@login_required
def review(request, slug, pk):
    event = _event(request, slug)
    ev = get_object_or_404(Evaluation.objects.select_related('assignment__juror', 'assignment__submission__project'), pk=pk, assignment__hackathon=event)
    return render(request, 'evaluations/review.html', _context(event, evaluation=ev, scores=ev.scores.select_related('criterion')))


@login_required
def prizes(request, slug):
    event = _event(request, slug)
    obj = get_object_or_404(Prize, hackathon=event, pk=request.GET['edit']) if request.GET.get('edit') else None
    form = PrizeForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'prize' else None, event=event, instance=obj)
    award_form = AwardForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'award' else None, event=event)
    if request.method == 'POST':
        try:
            if request.POST.get('action') == 'prize' and form.is_valid():
                services.save_prize(actor=request.user, event=event, data=form.cleaned_data, prize=obj)
            elif request.POST.get('action') == 'award' and award_form.is_valid():
                services.award(actor=request.user, **award_form.cleaned_data)
            else:
                return render(request, 'evaluations/prizes.html', _context(event, form=form, award_form=award_form, prizes=event.prizes.select_related('sponsorship__organization', 'award__submission__project')))
            messages.success(request, 'Récompense enregistrée.')
            return redirect('evaluations:prizes', slug=slug)
        except ValidationError as error:
            _error(request, error)
    return render(request, 'evaluations/prizes.html', _context(event, form=form, award_form=award_form, prizes=event.prizes.select_related('sponsorship__organization', 'award__submission__project')))


def results(request, slug):
    event = get_object_or_404(Hackathon, slug=slug)
    publications = event.result_publications.filter(published_at__isnull=False)
    publication = get_object_or_404(publications, version=request.GET['version']) if request.GET.get('version') else publications.first()
    awards = publication.awards.select_related('prize__sponsorship__organization') if publication else []
    winners = []
    for award in awards:
        row = next(r for r in publication.ranking if r['submission_id'] == award.submission_id)
        winners.append({'prize': award.prize, 'project': row['project'], 'team': row['team']})
    return render(request, 'evaluations/results.html', _context(event, publication=publication, publications=publications, winners=winners, private_workspace=False))
