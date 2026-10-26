from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from django.forms import formset_factory
from accounts.permissions import can_manage, require_organizer
from hackathons.models import Hackathon, EventPhase
from hackathons.views import visible_events
from hackathons.services import phase_is_open
from . import services
from .models import Registration, Team, TeamMembership, TeamInvitation, JoinRequest, TeamSkillNeed, Decision
from .forms import RegistrationForm, TeamForm, MessageForm, InvitationForm, NeedForm
from .forms import SkillDescriptionForm, SuggestedNeedForm


def context(request, slug, *, private=True):
    event = get_object_or_404(visible_events(request.user), slug=slug)
    if private:
        services.require_reader(request.user, event)
    reg = services.accepted_registration(request.user, event)
    return {'event': event, 'registration': reg, 'my_team': services.active_team(request.user, event),
        'organizer': can_manage(request.user, event), 'formation_open': services.formation_open(event),
        'registration_open': phase_is_open(event, EventPhase.Kind.REGISTRATION)}


def team_context(request, slug, pk):
    ctx = context(request, slug)
    team = get_object_or_404(Team.objects.select_related('hackathon', 'captain__user'), hackathon=ctx['event'], pk=pk)
    ctx.update(team=team, captain=services.is_captain(request.user, team),
        team_manager=services.is_captain(request.user, team) or ctx['organizer'])
    return ctx


def _form(request, form, ctx, title, *, hint='', button=None):
    return render(request, 'teams/form.html', {**ctx, 'form': form, 'title': title, 'hint': hint, 'button_label': button or _('Enregistrer')})


def _error(form, exc):
    form.add_error(None, ValidationError(exc.messages) if isinstance(exc, ValidationError) else _('Ces données existent déjà. Actualisez la page et réessayez.'))


@login_required
def mine(request):
    rows = request.user.registrations.select_related('hackathon').order_by('-created_at')
    for reg in rows:
        reg.current_team = services.active_team(request.user, reg.hackathon)
    return render(request, 'teams/mine.html', {'registrations': rows})


@login_required
@require_http_methods(['GET', 'POST'])
def register(request, slug):
    ctx = context(request, slug, private=False)
    target_id = request.GET.get('team', '')
    target = get_object_or_404(Team, pk=target_id, hackathon=ctx['event'], closed_at__isnull=True) if target_id.isdigit() else None
    if target:
        ctx['resume_team'] = target
        if not ctx['formation_open'] or not target.recruiting or not target.places_left:
            messages.info(request, _('Cette équipe ne recrute plus. Vous pouvez découvrir les autres équipes.'))
            return redirect(target)
    if ctx['registration']:
        return redirect('teams:apply', slug=slug, pk=target.pk) if target else redirect('teams:list', slug=slug)
    form = RegistrationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.register(actor=request.user, event=ctx['event'], **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            if target:
                messages.success(request, _('Inscription confirmée. Vous pouvez maintenant envoyer votre candidature.'))
                return redirect('teams:apply', slug=slug, pk=target.pk)
            messages.success(request, _('Inscription confirmée ! Trouvez votre équipe ou créez la vôtre.'))
            return redirect('teams:list', slug=slug)
    return _form(request, form, ctx, _('Participer à ce hackathon'), button=_('Confirmer mon inscription'))


@login_required
@require_http_methods(['GET', 'POST'])
def cancel(request, slug, pk):
    ctx = context(request, slug, private=False)
    reg = get_object_or_404(Registration, hackathon=ctx['event'], pk=pk)
    if reg.user_id != request.user.pk and not ctx['organizer']:
        raise PermissionDenied
    if request.method == 'POST':
        try:
            services.cancel_registration(actor=request.user, registration=reg)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        else:
            messages.success(request, _('Inscription annulée.'))
        return redirect('teams:manage', slug=slug) if ctx['organizer'] and reg.user_id != request.user.pk else redirect('teams:mine')
    return render(request, 'teams/confirm.html', {**ctx, 'title': _('Annuler cette inscription ?'),
        'explanation': _('Le rôle participant sera retiré pour cette édition uniquement. Vous devez d’abord quitter votre équipe.'), 'subject': reg.user})


def listing(request, slug):
    ctx = context(request, slug, private=False)
    teams = services.teams_with_counts(ctx['event'])
    query = request.GET.get('q', '').strip()
    if query:
        teams = teams.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if request.GET.get('open'):
        teams = teams.filter(recruiting=True, active_count__lt=ctx['event'].max_team_size)
    skill = request.GET.get('skill', '')
    if skill.isdigit():
        teams = teams.filter(skill_needs__skill_id=skill)
    from accounts.models import Skill
    return render(request, 'teams/list.html', {**ctx, 'page_obj': Paginator(teams, 12).get_page(request.GET.get('page')),
        'skills': Skill.objects.filter(teamskillneed__team__hackathon=ctx['event']).distinct()})


def detail(request, slug, pk):
    public_ctx = context(request, slug, private=False)
    if not services.can_read(request.user, public_ctx['event']):
        team = get_object_or_404(Team, pk=pk, hackathon=public_ctx['event'], closed_at__isnull=True)
        return render(request, 'teams/preview.html', {**public_ctx, 'team': team,
            'needs': team.skill_needs.select_related('skill')})
    ctx = team_context(request, slug, pk)
    team = ctx['team']
    members = services.active_members(team).prefetch_related('registration__user__user_skills__skill')
    own_member = members.filter(registration__user=request.user).first()
    requests = team.joinrequests.select_related('registration__user') if ctx['team_manager'] else []
    invitations = team.teaminvitations.select_related('registration__user') if ctx['team_manager'] else []
    return render(request, 'teams/detail.html', {**ctx, 'members': members, 'own_member': own_member,
        'needs': services.skill_coverage(team), 'join_requests': requests, 'invitations': invitations,
        'history': team.history.select_related('actor', 'registration__user')[:30] if ctx['team_manager'] else [],
        'applied': JoinRequest.objects.filter(team=team, registration=ctx['registration'], status=Decision.PENDING).exists() if ctx['registration'] else False})


@login_required
@require_http_methods(['GET', 'POST'])
def create(request, slug):
    ctx = context(request, slug)
    if ctx['my_team']:
        return redirect(ctx['my_team'])
    form = TeamForm(request.POST if request.method == 'POST' else None, initial={'recruiting': True})
    del form.fields['recruiting']
    if request.method == 'POST' and form.is_valid():
        try:
            team = services.create_team(actor=request.user, event=ctx['event'], name=form.cleaned_data['name'], description=form.cleaned_data['description'])
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Votre équipe est créée. Ajoutez vos besoins et invitez des coéquipiers.'))
            return redirect(team)
    return _form(request, form, ctx, _('Créer mon équipe'), hint=_('Vous serez capitaine et premier membre. Vous pourrez recruter ensuite.'))


@login_required
@require_http_methods(['GET', 'POST'])
def edit(request, slug, pk):
    ctx = team_context(request, slug, pk)
    if not ctx['team_manager']:
        raise PermissionDenied
    form = TeamForm(request.POST if request.method == 'POST' else None, instance=ctx['team'])
    if request.method == 'POST' and form.is_valid():
        try:
            team = services.update_team(actor=request.user, team=ctx['team'], **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Équipe mise à jour.'))
            return redirect(team)
    return _form(request, form, ctx, _('Modifier l’équipe'))


@login_required
@require_http_methods(['GET', 'POST'])
def apply(request, slug, pk):
    public_ctx = context(request, slug, private=False)
    target = get_object_or_404(Team, pk=pk, hackathon=public_ctx['event'], closed_at__isnull=True)
    if not public_ctx['registration']:
        return redirect(reverse('teams:register', kwargs={'slug': slug}) + f'?team={target.pk}')
    ctx = team_context(request, slug, pk)
    if ctx['my_team'] or not ctx['formation_open'] or not target.recruiting or not target.places_left:
        messages.info(request, _('Cette candidature n’est pas disponible : vérifiez votre équipe, les places et le calendrier.'))
        return redirect(target)
    if JoinRequest.objects.filter(team=target, registration=ctx['registration'], status=Decision.PENDING).exists():
        messages.info(request, _('Votre candidature est déjà en attente.'))
        return redirect('teams:inbox', slug=slug)
    form = MessageForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.recruit(actor=request.user, team=ctx['team'], **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Candidature envoyée. Le capitaine pourra vous répondre.'))
            return redirect('teams:inbox', slug=slug)
    return _form(request, form, ctx, _('Rejoindre cette équipe'), hint=_('Votre place est confirmée uniquement après acceptation.'), button=_('Envoyer ma candidature'))


@login_required
@require_http_methods(['GET', 'POST'])
def invite(request, slug, pk):
    ctx = team_context(request, slug, pk)
    if not ctx['team_manager']:
        raise PermissionDenied
    initial = {'registration': request.GET.get('participant')} if request.GET.get('participant', '').isdigit() else {}
    form = InvitationForm(request.POST if request.method == 'POST' else None, candidates=services.eligible_candidates(actor=request.user, team=ctx['team']), initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            services.recruit(actor=request.user, team=ctx['team'], **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Invitation envoyée. Aucune place n’est réservée avant acceptation.'))
            return redirect(ctx['team'])
    return _form(request, form, ctx, _('Inviter un participant'), hint=_('L’invitation expire après 7 jours ou à la fin de la formation des équipes.'), button=_('Envoyer l’invitation'))


@login_required
def inbox(request, slug):
    ctx = context(request, slug)
    invitations = TeamInvitation.objects.filter(registration=ctx['registration']).select_related('team', 'team__hackathon') if ctx['registration'] else []
    requests = JoinRequest.objects.filter(registration=ctx['registration']).select_related('team', 'team__hackathon') if ctx['registration'] else []
    return render(request, 'teams/inbox.html', {**ctx, 'invitations': invitations, 'join_requests': requests, 'now': timezone.now()})


@login_required
@require_POST
def decide(request, slug, kind, pk, decision):
    ctx = context(request, slug)
    model = {'invitation': TeamInvitation, 'application': JoinRequest}.get(kind)
    if not model:
        from django.http import Http404
        raise Http404
    record = get_object_or_404(model.objects.select_related('team__hackathon', 'registration__user'), team__hackathon=ctx['event'], pk=pk)
    try:
        services.decide(actor=request.user, record=record, decision=decision)
    except (ValidationError, IntegrityError) as exc:
        messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else _('Cette équipe vient de changer. Actualisez la page.'))
    else:
        messages.success(request, _('Décision enregistrée.'))
    return redirect(record.team) if ctx['organizer'] or services.is_captain(request.user, record.team) else redirect('teams:inbox', slug=slug)


@login_required
@require_http_methods(['GET', 'POST'])
def member_action(request, slug, pk, member_pk, action):
    ctx = team_context(request, slug, pk)
    member = get_object_or_404(TeamMembership.objects.select_related('registration__user'), team=ctx['team'], pk=member_pk, ended_at__isnull=True)
    if action not in ('leave', 'transfer') or (not ctx['team_manager'] and (action != 'leave' or member.registration.user_id != request.user.pk)):
        raise PermissionDenied
    title = _('Transférer le rôle de capitaine ?') if action == 'transfer' else _('Retirer ce membre ?') if member.registration.user_id != request.user.pk else _('Quitter cette équipe ?')
    if request.method == 'POST':
        try:
            operation = services.transfer_captain if action == 'transfer' else services.leave_team
            operation(actor=request.user, team=ctx['team'], membership=member)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        else:
            messages.success(request, _('Composition de l’équipe mise à jour.'))
        return redirect('teams:list', slug=slug) if ctx['team'].closed_at else redirect(ctx['team'])
    return render(request, 'teams/confirm.html', {**ctx, 'title': title, 'subject': member.registration.user,
        'explanation': _('Cette action est enregistrée dans l’historique. Un capitaine doit transférer son rôle avant de quitter une équipe qui compte d’autres membres.')})


@login_required
@require_http_methods(['GET', 'POST'])
def need_edit(request, slug, pk, need_pk=None):
    if need_pk is None and (request.GET.get('mode') == 'idea' or request.POST.get('action') in ('analyze', 'save')):
        return suggest_needs(request, slug, pk)
    ctx = team_context(request, slug, pk)
    if not ctx['team_manager']:
        raise PermissionDenied
    need = get_object_or_404(TeamSkillNeed, team=ctx['team'], pk=need_pk) if need_pk else None
    form = NeedForm(request.POST if request.method == 'POST' else None, instance=need)
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_need(actor=request.user, team=ctx['team'], need=need, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            _error(form, exc)
        else:
            messages.success(request, _('Besoin de compétence enregistré.'))
            return redirect(ctx['team'])
    if need is None:
        return render(request, 'teams/need_add.html', {**ctx, 'form': form, 'need_mode': 'manual'})
    return _form(request, form, ctx, _('Modifier un besoin'))


@login_required
@require_http_methods(['GET','POST'])
def suggest_needs(request, slug, pk):
    from accounts.models import Skill
    from .skill_suggestions import suggest
    ctx = team_context(request,slug,pk)
    if not ctx['team_manager']:
        raise PermissionDenied
    key = f'm2-need-preview-{ctx["team"].pk}'
    selection = None
    state = None
    retry = 0
    description_form = SkillDescriptionForm(initial={'text':ctx['team'].description})
    action = request.POST.get('action','analyze')
    FormSet = formset_factory(SuggestedNeedForm,extra=0,max_num=13,validate_max=True,absolute_max=13)
    if request.method=='POST' and action=='save':
        preview = request.session.get(key,{})
        if preview.get('expires',0) < timezone.now().timestamp():
            messages.info(request,_('Cette proposition a expiré. Analysez à nouveau votre description.'))
            return redirect('teams:need-suggestions',slug=slug,pk=pk)
        allowed = Skill.objects.filter(name__in=preview.get('labels',[]))
        selection = FormSet(request.POST,prefix='needs',form_kwargs={'allowed_skills':allowed})
        description_form = SkillDescriptionForm(initial={'text':preview.get('text','')})
        state = 'ready'
        if selection.is_valid():
            proposals = [{'skill':f.cleaned_data['skill'],'level':f.cleaned_data['level'],'priority':f.cleaned_data['priority']}
                for f in selection if f.cleaned_data.get('selected')]
            if not proposals:
                messages.info(request,_('Sélectionnez au moins une compétence à ajouter.'))
            else:
                try:
                    count = services.save_suggested_needs(actor=request.user,team=ctx['team'],proposals=proposals)
                except (ValidationError,IntegrityError) as exc:
                    messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else _('Actualisez la page et réessayez.'))
                else:
                    request.session.pop(key,None)
                    messages.success(request,_('%(count)s besoin(s) ajouté(s). Les besoins existants sont conservés.') % {'count':count})
                    return redirect(ctx['team'])
    elif request.method=='POST':
        request.session.pop(key,None)
        description_form = SkillDescriptionForm(request.POST)
        if description_form.is_valid():
            result = suggest(description_form.cleaned_data['text'])
            state = result['state']
            if state=='ready':
                proposed = [r['label'] for r in result['suggestions']]
                existing = set(ctx['team'].skill_needs.values_list('skill__name',flat=True))
                rows = list(Skill.objects.filter(name__in=proposed).exclude(name__in=existing))
                order = {name:i for i,name in enumerate(proposed)}
                rows.sort(key=lambda s:order[s.name])
                request.session[key] = {'labels':[s.name for s in rows], 'text':description_form.cleaned_data['text'],
                    'sources':{r['label']:r.get('source','ml') for r in result['suggestions']},
                    'expires':timezone.now().timestamp()+1200}
                selection = FormSet(initial=[{'skill':s.pk} for s in rows],prefix='needs',
                    form_kwargs={'allowed_skills':Skill.objects.filter(pk__in=[s.pk for s in rows])})
                ctx['already_declared'] = sorted(set(proposed)&existing)
            elif state=='warming':
                try:
                    retry = min(5,max(0,int(request.POST.get('retry','0'))))+1
                except ValueError:
                    retry = 6
    if selection is not None:
        sources = request.session.get(key,{}).get('sources',{})
        for f in selection:
            f.suggestion_source = sources.get(str(f.skill_label),'ml')
    return render(request,'teams/need_suggestions.html',{**ctx,'need_mode':'idea','description_form':description_form,
        'selection':selection,'suggestion_state':state,'retry':retry,'auto_retry':state=='warming' and retry<=5})


@login_required
@require_http_methods(['GET', 'POST'])
def need_delete(request, slug, pk, need_pk):
    ctx = team_context(request, slug, pk)
    if not ctx['team_manager']:
        raise PermissionDenied
    need = get_object_or_404(TeamSkillNeed, pk=need_pk, team=ctx['team'])
    if request.method == 'POST':
        try:
            services.delete_need(actor=request.user, need=need)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        return redirect(ctx['team'])
    return render(request, 'teams/confirm.html', {**ctx, 'title': _('Retirer ce besoin ?'), 'subject': need.skill, 'explanation': _('Les compétences personnelles des membres seront conservées.')})


@login_required
def candidates(request, slug, pk):
    ctx = team_context(request, slug, pk)
    if not ctx['team_manager']:
        raise PermissionDenied
    ranking_mode = 'skills' if request.GET.get('ranking') == 'skills' else 'hybrid'
    candidates, baseline, remaining_needs = services.recommendation_comparison(actor=request.user, team=ctx['team'], mode=ranking_mode)
    matching_state = candidates[0]['matching_state'] if candidates else 'empty'
    pending_invitations = set(TeamInvitation.objects.filter(team=ctx['team'], status=Decision.PENDING, expires_at__gt=timezone.now()).values_list('registration_id', flat=True))
    pending_applications = set(JoinRequest.objects.filter(team=ctx['team'], status=Decision.PENDING).values_list('registration_id', flat=True))
    for candidate in candidates:
        candidate['pending_invitation'] = candidate['registration'].pk in pending_invitations
        candidate['pending_application'] = candidate['registration'].pk in pending_applications
    query = request.GET.get('q', '').strip().casefold()
    if query:
        def matches_query(c):
            return query in c['registration'].user.get_full_name().casefold() or query in c['registration'].user.username.casefold() or any(query in s.skill.name.casefold() for s in c['registration'].user.user_skills.all())
        candidates = [c for c in candidates if matches_query(c)]
        baseline = [c for c in baseline if matches_query(c)]
    positions = {c['registration'].pk: i for i, c in enumerate(baseline, 1)}
    for position, candidate in enumerate(candidates, 1):
        candidate['position'] = position
        candidate['skills_position'] = positions[candidate['registration'].pk]
        candidate['rank_gain'] = candidate['skills_position'] - position if matching_state == 'ready' else 0
    return render(request, 'teams/candidates.html', {**ctx, 'page_obj': Paginator(candidates, 12).get_page(request.GET.get('page')),
        'matching_state': matching_state, 'remaining_needs': remaining_needs, 'ranking_mode': ranking_mode})


@login_required
def manage(request, slug):
    ctx = context(request, slug)
    require_organizer(request.user, ctx['event'], mutable=False)
    registrations = ctx['event'].registrations.select_related('user')
    query = request.GET.get('q', '').strip()
    if query:
        registrations = registrations.filter(Q(user__username__icontains=query) | Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query))
    for reg in registrations:
        reg.current_team = services.active_team(reg.user, ctx['event'])
    event = ctx['event']
    counts = services.metrics(event)
    if event.status == Hackathon.Status.ARCHIVED:
        snapshot = event.archive_metrics.get('modules', {}).get('M2', {})
        counts = snapshot.get('counts') if snapshot.get('available') else None
    return render(request, 'teams/manage.html', {**ctx, 'registrations': registrations, 'teams': services.teams_with_counts(event), 'counts': counts})
