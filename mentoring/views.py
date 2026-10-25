from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, TemplateView, UpdateView

from accounts.models import AssignmentStatus, Role, RoleAssignment
from accounts.permissions import can_manage
from hackathons.models import Hackathon
from teams import services as team_services
from teams.models import Team
from . import ai, services
from .forms import (FeedbackForm, MentorExpertiseForm, SessionReportForm, SkillFilterForm, SlotForm, SupportRequestForm,
    WorkshopForm)
from .models import (M4History, MentoringSession, MentorExpertise, MentorSlot, SupportRequest, Workshop,
    WorkshopRegistration)
from .permissions import MentorRequiredMixin, is_mentor


def paginate(request, items, per_page=10, param='page'):
    """One page of a list; each list of a screen has its own query parameter so several can coexist.
    The page carries ready-made `prev_url` / `next_url` that keep the other parameters of the address."""
    page = Paginator(items, per_page).get_page(request.GET.get(param))

    def url(number):
        query = request.GET.copy()
        query[param] = number
        return '?' + query.urlencode()

    page.prev_url = url(page.previous_page_number()) if page.has_previous() else None
    page.next_url = url(page.next_page_number()) if page.has_next() else None
    return page


def group_by_day(items, attr='start'):
    days = []
    for item in items:
        day = timezone.localtime(getattr(item, attr)).date()
        if not days or days[-1]['day'] != day:
            days.append({'day': day, 'items': []})
        days[-1]['items'].append(item)
    return days


class ExpertiseListView(MentorRequiredMixin, TemplateView):
    template_name = 'mentoring/expertise_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['expertises'] = MentorExpertise.objects.filter(user=self.request.user).select_related('skill')
        context['assignments'] = self.request.user.role_assignments.filter(
            role=Role.MENTOR, status=AssignmentStatus.ACTIVE).select_related('hackathon')
        return context


class OwnExpertiseMixin(MentorRequiredMixin):
    success_url = reverse_lazy('mentoring:expertise-list')

    def get_queryset(self):
        return MentorExpertise.objects.filter(user=self.request.user)


class ExpertiseCreateView(OwnExpertiseMixin, SuccessMessageMixin, CreateView):
    form_class = MentorExpertiseForm
    template_name = 'shared/form.html'
    success_message = _('Expertise ajoutée.')
    extra_context = {'title': _('Ajouter une expertise'), 'button_label': _('Ajouter')}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = MentorExpertise(user=self.request.user)
        return kwargs


class ExpertiseUpdateView(OwnExpertiseMixin, SuccessMessageMixin, UpdateView):
    form_class = MentorExpertiseForm
    template_name = 'shared/form.html'
    success_message = _('Niveau mis à jour.')
    extra_context = {'title': _('Modifier mon niveau')}


class ExpertiseDeleteView(OwnExpertiseMixin, DeleteView):
    template_name = 'mentoring/expertise_delete.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _('Expertise retirée.'))
        return response


# ------------------------------------------------------------------ slots
class SlotListView(MentorRequiredMixin, TemplateView):
    template_name = 'mentoring/slot_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        own = MentorSlot.objects.filter(mentor=self.request.user).select_related('hackathon').prefetch_related('sessions')
        upcoming = paginate(self.request, own.filter(end__gt=now, withdrawn_at__isnull=True).order_by('start'), 15, 'page_up')
        context['days'] = [{'day': g['day'], 'slots': g['items']} for g in group_by_day(list(upcoming))]
        context['upcoming'] = upcoming
        context['upcoming_count'] = upcoming.paginator.count
        context['history'] = paginate(self.request, own.filter(Q(end__lte=now) | Q(withdrawn_at__isnull=False)).order_by('-start'), 10, 'page_past')
        context['can_create'] = services.mentor_open_hackathons(self.request.user).exists()
        return context


class SlotFormMixin(MentorRequiredMixin, FormView):
    form_class = SlotForm
    template_name = 'shared/form.html'
    success_url = reverse_lazy('mentoring:slot-list')

    def get_slot(self):
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(user=self.request.user, slot=self.get_slot())
        return kwargs

    def run(self, form):
        raise NotImplementedError

    def form_valid(self, form):
        try:
            self.run(form)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        except PermissionDenied as exc:
            form.add_error(None, str(exc) or _('Action non autorisée.'))
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.get_success_url())


class SlotCreateView(SlotFormMixin):
    success_message = _('Créneau publié.')
    extra_context = {'title': _('Publier un créneau'), 'button_label': _('Publier le créneau')}

    def run(self, form):
        services.create_slot(actor=self.request.user, hackathon=form.cleaned_data['hackathon'],
            start=form.cleaned_data['start'], end=form.cleaned_data['end'])


class SlotUpdateView(SlotFormMixin):
    success_message = _('Créneau modifié.')
    extra_context = {'title': _('Modifier le créneau'), 'button_label': _('Enregistrer')}

    def get_slot(self):
        if not hasattr(self, '_slot'):
            self._slot = get_object_or_404(MentorSlot, pk=self.kwargs['pk'], mentor=self.request.user)
        return self._slot

    def run(self, form):
        services.update_slot(actor=self.request.user, slot=self.get_slot(),
            start=form.cleaned_data['start'], end=form.cleaned_data['end'])


class SlotCancelView(MentorRequiredMixin, View):
    template_name = 'mentoring/slot_cancel.html'

    def get_slot(self):
        return get_object_or_404(MentorSlot, pk=self.kwargs['pk'], mentor=self.request.user)

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {'slot': self.get_slot()})

    def post(self, request, *args, **kwargs):
        try:
            services.cancel_slot(actor=request.user, slot=self.get_slot())
            messages.success(request, _('Créneau annulé.'))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        return redirect(reverse('mentoring:slot-list'))


# -------------------------------------------------------------- workshops
def error_text(exc):
    """The message of a service refusal, whatever its type."""
    if isinstance(exc, ValidationError):
        return ' '.join(exc.messages)
    return str(exc) or _('Action non autorisée.')


class PublisherRequiredMixin(LoginRequiredMixin):
    """Workshops are published by the mentor who leads them, or by an organizer of the edition."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (is_mentor(request.user) or services.organized_hackathons(request.user).exists()):
            raise PermissionDenied(_('Seuls un mentor ou un organisateur peuvent gérer les ateliers.'))
        return super().dispatch(request, *args, **kwargs)


class WorkshopListView(LoginRequiredMixin, TemplateView):
    """Workshops of the editions in which the user holds a role, with seats and registration status."""
    template_name = 'mentoring/workshop_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user, now = self.request.user, timezone.now()
        registered = Count('registrations', filter=Q(registrations__status=WorkshopRegistration.Status.REGISTERED), distinct=True)
        upcoming = paginate(self.request, services.visible_workshops(user).annotate(registered=registered).filter(
            status=Workshop.Status.PUBLISHED, end__gt=now).order_by('start'), 12, 'page_up')
        mine = set(WorkshopRegistration.objects.filter(registration__user=user,
            status=WorkshopRegistration.Status.REGISTERED).values_list('workshop_id', flat=True))
        for workshop in upcoming:
            workshop.seats_left = max(workshop.capacity - workshop.registered, 0)
            workshop.is_registered = workshop.pk in mine
        organizer = services.organized_hackathons(user)
        context.update(
            days=[{'day': g['day'], 'workshops': g['items']} for g in group_by_day(list(upcoming))],
            upcoming=upcoming, upcoming_count=upcoming.paginator.count, is_trainer=is_mentor(user), now=now,
            led=paginate(self.request, Workshop.objects.filter(trainer=user).select_related('hackathon').annotate(registered=registered).order_by('-start'), 8, 'page_led'),
            managed=paginate(self.request, Workshop.objects.filter(hackathon__in=organizer).select_related('hackathon', 'trainer').annotate(registered=registered).order_by('-start'), 8, 'page_managed'),
            is_organizer=organizer.exists(), can_create=services.publishable_hackathons(user).exists())
        return context


class WorkshopDetailView(LoginRequiredMixin, DetailView):
    template_name = 'mentoring/workshop_detail.html'
    context_object_name = 'workshop'

    def get_queryset(self):
        return services.visible_workshops(self.request.user)  # other hackathons: 404, existence stays private

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workshop, user, now = self.object, self.request.user, timezone.now()
        event = workshop.hackathon
        row = WorkshopRegistration.objects.filter(workshop=workshop, registration__user=user).first()
        registered, free = services.workshop_seats(workshop)
        is_trainer, is_organizer = workshop.trainer_id == user.pk, can_manage(user, event)
        open_for_changes = (workshop.status == Workshop.Status.PUBLISHED and workshop.start > now
            and event.status in services.OPEN_STATUSES)
        is_registered = bool(row and row.status == WorkshopRegistration.Status.REGISTERED)
        show_participants = is_trainer or is_organizer
        context.update(
            registered=registered, seats_left=free, is_trainer=is_trainer, is_organizer=is_organizer,
            my_row=row, is_registered=is_registered,
            has_registration=bool(team_services.accepted_registration(user, event)),
            can_register=bool(team_services.accepted_registration(user, event)) and open_for_changes and not is_registered and free > 0,
            can_unregister=is_registered and workshop.start > now,
            can_edit=(is_organizer or is_trainer) and open_for_changes,
            show_participants=show_participants,
            attendance_open=show_participants and workshop.status == Workshop.Status.PUBLISHED and workshop.start <= now,
            rows=workshop.registrations.filter(status=WorkshopRegistration.Status.REGISTERED).select_related('registration__user').order_by('registration__user__username') if show_participants else [])
        return context


class WorkshopPostView(LoginRequiredMixin, View):
    """Base of the one-click actions: POST only, the workshop must be visible to the user."""
    http_method_names = ['post']
    success_message = ''

    def get_workshop(self):
        return get_object_or_404(services.visible_workshops(self.request.user), pk=self.kwargs['pk'])

    def run(self, workshop):
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        workshop = self.get_workshop()
        try:
            self.run(workshop)
            messages.success(request, self.success_message)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, error_text(exc))
        return redirect(workshop)


class WorkshopRegisterView(WorkshopPostView):
    success_message = _('Inscription confirmée.')

    def run(self, workshop):
        services.register_to_workshop(actor=self.request.user, workshop=workshop)


class WorkshopUnregisterView(WorkshopPostView):
    success_message = _('Inscription annulée.')

    def run(self, workshop):
        services.cancel_workshop_registration(actor=self.request.user, workshop=workshop)


class WorkshopAttendanceView(WorkshopPostView):
    success_message = _('Présence enregistrée.')

    def run(self, workshop):
        row = get_object_or_404(WorkshopRegistration, pk=self.kwargs['registration_pk'], workshop=workshop)
        services.mark_attendance(actor=self.request.user, workshop_registration=row, attendance=self.request.POST.get('attendance', ''))


class WorkshopFormMixin(PublisherRequiredMixin, FormView):
    form_class = WorkshopForm
    template_name = 'mentoring/workshop_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(ai_enabled=ai.is_configured() and self.get_workshop() is None, suggest_url=reverse('mentoring:workshop-suggest'))
        return context

    def get_workshop(self):
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(user=self.request.user, workshop=self.get_workshop())
        return kwargs

    def run(self, form):
        raise NotImplementedError

    def form_valid(self, form):
        try:
            self.workshop = self.run(form)
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else error_text(exc))
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.workshop.get_absolute_url())

    def workshop_fields(self, form):
        data = form.cleaned_data
        fields = {name: data[name] for name in ('trainer', 'title', 'description', 'capacity', 'start', 'end', 'location')}
        workshop = self.get_workshop()
        fields['url'] = workshop.url if workshop else ''  # the form only takes a room; an existing online link is kept
        return fields


SUGGESTIONS_PER_HOUR = 12


class WorkshopSuggestView(PublisherRequiredMixin, View):
    """Gemini proposes a theme and a description for the chosen hackathon; the form is filled, nothing is saved."""

    def post(self, request, *args, **kwargs):
        try:
            hackathon = services.publishable_hackathons(request.user).get(pk=int(request.POST.get('hackathon', '')))
        except (ValueError, Hackathon.DoesNotExist):
            return JsonResponse({'error': str(_('Choisissez d’abord un hackathon.'))}, status=400)
        key = f'm4-suggest-{request.user.pk}'
        used = cache.get(key, 0)
        if used >= SUGGESTIONS_PER_HOUR:
            return JsonResponse({'error': str(_('Trop de suggestions pour le moment, réessayez dans une heure.'))}, status=429)
        cache.set(key, used + 1, 3600)
        try:
            suggestion, latency_ms = ai.suggest_workshop(hackathon)
        except ai.SuggestionUnavailable:
            return JsonResponse({'error': str(ai.UNAVAILABLE)}, status=503)
        suggestion['latency_ms'] = latency_ms
        suggestion['message'] = str(_('Suggestion de l’IA : relisez et corrigez avant de publier.'))
        return JsonResponse(suggestion)


class WorkshopCreateView(WorkshopFormMixin):
    success_message = _('Atelier publié.')
    extra_context = {'title': _('Publier un atelier'), 'button_label': _('Publier l’atelier')}

    def run(self, form):
        return services.create_workshop(actor=self.request.user, hackathon=form.cleaned_data['hackathon'], **self.workshop_fields(form))


class WorkshopUpdateView(WorkshopFormMixin):
    success_message = _('Atelier modifié.')
    extra_context = {'title': _('Modifier l’atelier'), 'button_label': _('Enregistrer')}

    def get_workshop(self):
        if not hasattr(self, '_workshop'):
            self._workshop = get_object_or_404(services.manageable_workshops(self.request.user), pk=self.kwargs['pk'])
        return self._workshop

    def run(self, form):
        return services.update_workshop(actor=self.request.user, workshop=self.get_workshop(), **self.workshop_fields(form))


class WorkshopCancelView(PublisherRequiredMixin, View):
    template_name = 'mentoring/workshop_cancel.html'

    def get_workshop(self):
        return get_object_or_404(services.manageable_workshops(self.request.user), pk=self.kwargs['pk'])

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {'workshop': self.get_workshop()})

    def post(self, request, *args, **kwargs):
        workshop = self.get_workshop()
        try:
            services.cancel_workshop(actor=request.user, workshop=workshop)
            messages.success(request, _('Atelier annulé.'))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, error_text(exc))
        return redirect(reverse('mentoring:workshop-list'))


# ----------------------------------------------------------- support center
class SupportListView(LoginRequiredMixin, TemplateView):
    template_name = 'mentoring/support_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        by_priority = {'rank': services.PRIORITY_RANK}
        mine = paginate(self.request, services.team_requests(user).annotate(**by_priority).order_by('rank', '-created_at'), 8, 'page_mine')
        coached = paginate(self.request, services.coached_requests(user).annotate(**by_priority).order_by('rank', '-created_at'), 8, 'page_coached')
        insights = []
        for event in services.organized_hackathons(user).order_by('-start_date')[:10]:
            block = services.support_insights(event)
            block['requests_page'] = paginate(self.request, block['requests'], 8, f'page_event{event.pk}')
            insights.append(block)
        context.update(my_requests=mine, coached_requests=coached, insights=insights, is_trainer=is_mentor(user),
            can_ask=bool(services.requestable_teams(user)),
            has_team=Team.objects.filter(closed_at__isnull=True, memberships__ended_at__isnull=True,
                memberships__registration__user=user).exists())
        return context


class SupportCreateView(LoginRequiredMixin, FormView):
    form_class = SupportRequestForm
    template_name = 'mentoring/support_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if self.request.method == 'GET' and self.request.GET.get('team', '').isdigit():
            kwargs['initial'] = {'team': int(self.request.GET['team'])}
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_ask'] = bool(services.requestable_teams(self.request.user))
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            support_request = services.open_request(actor=self.request.user, team=data['team'], subject=data['subject'],
                description=data['description'], skill=data['skill'], priority=data['priority'])
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else error_text(exc))
            return self.form_invalid(form)
        messages.success(self.request, _('Votre demande d’aide est ouverte.'))
        return redirect(support_request)


class VisibleRequestMixin(LoginRequiredMixin):
    """A request that the user may not see does not exist for them (404): confidentiality by the query."""

    def get_support_request(self):
        return get_object_or_404(services.visible_requests(self.request.user), pk=self.kwargs['pk'])


class SupportDetailView(VisibleRequestMixin, TemplateView):
    template_name = 'mentoring/support_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        support_request, user = self.get_support_request(), self.request.user
        sessions = list(support_request.sessions.select_related('slot__mentor').order_by('-slot__start'))
        context.update(support_request=support_request, can_cancel=services.can_cancel_request(user, support_request),
            can_book=services.can_book(user, support_request), sessions=sessions,
            active_session=next((s for s in sessions if s.status == MentoringSession.Status.BOOKED), None),
            awaiting_feedback=next((s for s in sessions if services.can_give_feedback(user, s)), None),
            history=M4History.objects.filter(object_type='SupportRequest', object_id=support_request.pk).select_related('actor'))
        return context


class SupportCancelView(VisibleRequestMixin, View):
    template_name = 'mentoring/support_cancel.html'

    def get(self, request, *args, **kwargs):
        support_request = self.get_support_request()
        if not services.can_cancel_request(request.user, support_request):
            messages.error(request, _('Cette demande ne peut pas être annulée par vous, ou elle n’est plus ouverte.'))
            return redirect(support_request)
        return render(request, self.template_name, {'support_request': support_request})

    def post(self, request, *args, **kwargs):
        support_request = self.get_support_request()
        try:
            services.cancel_request(actor=request.user, request=support_request)
            messages.success(request, _('Demande annulée.'))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, error_text(exc))
        return redirect(support_request)


# ---------------------------------------------------------- booking a mentor
class SupportBookView(VisibleRequestMixin, TemplateView):
    """The real free slots for a request, by day. The skill filter only narrows the list, it never ranks."""
    template_name = 'mentoring/support_book.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        support_request = self.get_support_request()
        form = SkillFilterForm(self.request.GET or None)
        skill = form.cleaned_data['skill'] if form.is_valid() else None
        slots = list(services.bookable_slots(support_request, skill))
        context.update(support_request=support_request, filter_form=form, filtered=skill is not None,
            days=[{'day': g['day'], 'slots': g['items']} for g in group_by_day(slots)], slot_count=len(slots),
            can_book=services.can_book(self.request.user, support_request))
        return context


class SupportBookSlotView(VisibleRequestMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        support_request = self.get_support_request()
        slot = get_object_or_404(MentorSlot, pk=kwargs['slot_pk'], hackathon_id=support_request.hackathon_id)
        try:
            session = services.book_session(actor=request.user, request=support_request, slot=slot)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, error_text(exc))
            return redirect('mentoring:support-book', pk=support_request.pk)
        messages.success(request, _('Rendez-vous réservé.'))
        return redirect(session)


# ------------------------------------------------- appointments and sessions
class AppointmentsView(LoginRequiredMixin, TemplateView):
    template_name = 'mentoring/appointments.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        sessions = list(services.visible_sessions(self.request.user).order_by('-slot__start')[:300])
        upcoming = sorted((s for s in sessions if s.status == MentoringSession.Status.BOOKED and s.slot.end > now),
            key=lambda s: s.slot.start)
        past = [s for s in sessions if s not in upcoming]
        context.update(upcoming=paginate(self.request, upcoming, 10, 'page_up'), past=paginate(self.request, past, 10, 'page_past'),
            is_trainer=is_mentor(self.request.user))
        return context


class VisibleSessionMixin(LoginRequiredMixin):
    def get_session(self):
        return get_object_or_404(services.visible_sessions(self.request.user), pk=self.kwargs['pk'])


class SessionDetailView(VisibleSessionMixin, View):
    """One appointment: the mentor writes the report, the team gives its feedback. Forms are re-shown with their errors."""
    template_name = 'mentoring/session_detail.html'

    def build(self, session, report_form=None, feedback_form=None):
        user, now = self.request.user, timezone.now()
        event = session.slot.hackathon
        is_mentor_of = session.slot.mentor_id == user.pk
        is_organizer = can_manage(user, event)
        can_complete = services.can_complete_session(user, session)
        can_edit_report = (is_mentor_of and session.status == MentoringSession.Status.COMPLETED
            and session.request.status == SupportRequest.Status.IN_PROGRESS)
        can_feedback = services.can_give_feedback(user, session)
        if report_form is None and (can_complete or can_edit_report):
            report_form = SessionReportForm(initial={'report': session.report, 'private_notes': session.private_notes})
        if feedback_form is None and can_feedback:
            feedback_form = FeedbackForm()
        return {'session': session, 'support_request': session.request, 'is_mentor_of': is_mentor_of,
            'show_private': is_mentor_of or is_organizer, 'can_complete': can_complete, 'can_edit_report': can_edit_report,
            'can_feedback': can_feedback, 'can_cancel': services.can_cancel_session(user, session),
            'not_started': session.slot.start > now, 'report_form': report_form, 'feedback_form': feedback_form,
            'history': M4History.objects.filter(object_type='MentoringSession', object_id=session.pk).select_related('actor')}

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.build(self.get_session()))

    def post(self, request, *args, **kwargs):
        session, action = self.get_session(), request.POST.get('action')
        if action in ('complete', 'update_report'):
            form = SessionReportForm(request.POST)
            if form.is_valid():
                run = services.complete_session if action == 'complete' else services.update_report
                try:
                    run(actor=request.user, session=session, report=form.cleaned_data['report'],
                        private_notes=form.cleaned_data['private_notes'])
                    messages.success(request, _('Séance terminée.') if action == 'complete' else _('Compte rendu mis à jour.'))
                    return redirect(session)
                except (ValidationError, PermissionDenied) as exc:
                    form.add_error(None, exc if isinstance(exc, ValidationError) else error_text(exc))
            return render(request, self.template_name, self.build(session, report_form=form))
        if action == 'feedback':
            form = FeedbackForm(request.POST)
            if form.is_valid():
                try:
                    services.give_feedback(actor=request.user, session=session, rating=form.cleaned_data['rating'],
                        comment=form.cleaned_data['comment'], resolved=form.cleaned_data['resolved'])
                    messages.success(request, _('Merci pour votre retour.'))
                    return redirect(session)
                except (ValidationError, PermissionDenied) as exc:
                    form.add_error(None, exc if isinstance(exc, ValidationError) else error_text(exc))
            return render(request, self.template_name, self.build(session, feedback_form=form))
        messages.error(request, _('Action non autorisée.'))
        return redirect(session)


class SessionCancelView(VisibleSessionMixin, View):
    template_name = 'mentoring/session_cancel.html'

    def get(self, request, *args, **kwargs):
        session = self.get_session()
        if not services.can_cancel_session(request.user, session):
            messages.error(request, _('Ce rendez-vous ne peut pas être annulé par vous, ou il n’est plus possible de l’annuler.'))
            return redirect(session)
        return render(request, self.template_name, {'session': session})

    def post(self, request, *args, **kwargs):
        session = self.get_session()
        try:
            services.cancel_session(actor=request.user, session=session)
            messages.success(request, _('Rendez-vous annulé.'))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, error_text(exc))
        return redirect(session)


# ------------------------------------------------------------- menu entry
class MentoringEntryView(LoginRequiredMixin, View):
    """The "Mentorat" menu entry opens the page of the user's own role: no intermediate page to read."""

    def get(self, request, *args, **kwargs):
        user = request.user
        in_team = Team.objects.filter(closed_at__isnull=True, memberships__ended_at__isnull=True,
            memberships__registration__user=user).exists()
        if in_team:
            name = 'mentoring:support-list'
        elif is_mentor(user):
            name = 'mentoring:appointments'
        elif services.organized_hackathons(user).exists():
            name = 'mentoring:support-list'
        else:
            name = 'mentoring:workshop-list'
        return redirect(name)
