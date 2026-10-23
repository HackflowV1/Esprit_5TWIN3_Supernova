from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView, FormView
from django.views import View
from django.views.generic.edit import FormMixin
from accounts.models import Role, RoleAssignment
from accounts.forms import RoleForm
from accounts.services import set_role
from accounts.permissions import can_manage, can_create_hackathon, has_role, require_organizer, is_member
from .models import Hackathon, Track, Challenge, EventPhase, SponsorOrganization, Sponsorship
from .forms import HackathonForm
from . import services


def visible_events(user):
    queryset = Hackathon.objects.all()
    if user.is_authenticated and user.is_active:
        if user.is_superuser:
            return queryset
        return queryset.filter(Q(status__in=services.PUBLIC_STATUSES)
            | Q(role_assignments__user=user, role_assignments__status='ACTIVE')).distinct()
    return queryset.filter(status__in=services.PUBLIC_STATUSES)


class EventContextMixin:
    def get_event(self):
        if not hasattr(self, 'event'):
            self.event = get_object_or_404(Hackathon, slug=self.kwargs['slug'])
        return self.event

    def get_success_url(self):
        return reverse('hackathons:manage', kwargs={'slug': self.get_event().slug})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['event'] = self.get_event()
        return context


class OrganizerMixin(LoginRequiredMixin, EventContextMixin):
    mutable = True

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        require_organizer(request.user, self.get_event(), mutable=self.mutable)
        return super().dispatch(request, *args, **kwargs)


class HackathonListView(ListView):
    template_name = 'hackathons/list.html'
    context_object_name = 'events'
    paginate_by = 12

    def get_queryset(self):
        queryset = visible_events(self.request.user)
        q = self.request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
        status = self.request.GET.get('status')
        if status in Hackathon.Status.values:
            queryset = queryset.filter(status=status)
        fmt = self.request.GET.get('format')
        if fmt in Hackathon.Format.values:
            queryset = queryset.filter(format=fmt)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(statuses=Hackathon.Status.choices, formats=Hackathon.Format.choices,
            can_create=can_create_hackathon(self.request.user))
        return context


class HackathonDetailView(DetailView):
    template_name = 'hackathons/detail.html'
    context_object_name = 'event'

    def get_queryset(self):
        return visible_events(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        context.update(challenges=services.public_challenges(event).select_related('track', 'sponsorship__organization'),
            phases=event.phases.all(), partnerships=event.sponsorships.filter(status='CONFIRMED').select_related('organization'),
            can_manage=can_manage(self.request.user, event),
            can_propose=has_role(self.request.user, event, Role.SPONSOR_REPRESENTATIVE) and event.status != 'ARCHIVED')
        return context


class HackathonCreateView(LoginRequiredMixin, CreateView):
    form_class = HackathonForm
    template_name = 'shared/form.html'
    extra_context = {'title': _('Créer un hackathon')}

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_create_hackathon(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            self.object = services.create_hackathon(actor=self.request.user, event=form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else _('Conflit de données : vérifiez le slug.'))
            return self.form_invalid(form)
        messages.success(self.request, _('Hackathon créé ; rôle organisateur attribué.'))
        return redirect(self.object)


class HackathonUpdateView(OrganizerMixin, UpdateView):
    model = Hackathon
    form_class = HackathonForm
    template_name = 'shared/form.html'
    extra_context = {'title': _('Configurer le hackathon')}

    def get_object(self, queryset=None):
        return self.get_event()

    def form_valid(self, form):
        try:
            self.object = services.save_configuration(actor=self.request.user, event=form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else _('Conflit de données.'))
            return self.form_invalid(form)
        messages.success(self.request, _('Configuration enregistrée.'))
        return redirect(self.object)


class ManageView(OrganizerMixin, TemplateView):
    template_name = 'hackathons/manage.html'
    mutable = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.get_event()
        context.update(tracks=event.tracks.all(), phases=event.phases.all(),
            challenges=Challenge.objects.filter(track__hackathon=event).select_related('track'),
            partnerships=event.sponsorships.select_related('organization'),
            assignments=event.role_assignments.select_related('user'), errors=services.configuration_errors(event) if event.status != 'ARCHIVED' else [],
            history=event.history.select_related('actor')[:50])
        return context


class HistoryView(OrganizerMixin, ListView):
    template_name = 'hackathons/history.html'
    context_object_name = 'entries'
    paginate_by = 50
    mutable = False

    def get_queryset(self):
        return self.get_event().history.select_related('actor')


class LifecycleView(OrganizerMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            services.transition(actor=request.user, event=self.get_event(), target=kwargs['target'])
            messages.success(request, _('Statut mis à jour.'))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        return redirect(self.get_success_url())


class ResourceMixin(OrganizerMixin):
    template_name = 'shared/form.html'
    sponsor = False

    def get_queryset(self):
        event = self.get_event()
        if self.model == Challenge:
            return self.model.objects.filter(track__hackathon=event)
        return self.model.objects.filter(hackathon=event)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if not kwargs.get('instance'):
            if self.model == Challenge:
                kwargs['instance'] = Challenge(proposed_by=self.request.user)
            else:
                kwargs['instance'] = self.model(hackathon=self.get_event())
        if self.model == Challenge:
            kwargs.update(event=self.get_event(), user=self.request.user, sponsor=self.sponsor)
        return kwargs

    def form_valid(self, form):
        resource = form.save(commit=False)
        try:
            if self.sponsor:
                self.object = services.propose_challenge(actor=self.request.user, challenge=resource)
            else:
                self.object = services.save_resource(actor=self.request.user, resource=resource,
                    action='Création' if not resource.pk else 'Modification')
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else _('Conflit : cet élément existe déjà.'))
            return self.form_invalid(form)
        messages.success(self.request, _('Challenge enregistré ; validation requise.') if self.model == Challenge else _('Configuration enregistrée.'))
        return redirect(self.get_success_url())


class ResourceCreateView(ResourceMixin, CreateView):
    pass


class ResourceUpdateView(ResourceMixin, UpdateView):
    pass


class ResourceDeleteView(ResourceMixin, DeleteView):
    template_name = 'shared/confirm_delete.html'

    def get_form_kwargs(self):
        return FormMixin.get_form_kwargs(self)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                event = Hackathon.objects.select_for_update().get(pk=self.get_event().pk)
                require_organizer(self.request.user, event)
                obj = self.get_object()
                if event.status != Hackathon.Status.DRAFT or (isinstance(obj, Challenge) and obj.status != Challenge.Status.DRAFT):
                    raise ValidationError(_('Suppression réservée aux brouillons ; utilisez le retrait ou l’archivage.'))
                label, pk = str(obj), obj.pk
                obj.delete()
                services.record(event, self.request.user, 'Suppression', label, pk=pk)
        except (ValidationError, ProtectedError) as exc:
            messages.error(self.request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else _('Élément référencé : suppression impossible.'))
        return redirect(self.get_success_url())


class SponsorProposalView(ResourceCreateView):
    model = Challenge
    sponsor = True

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not has_role(request.user, self.get_event(), Role.SPONSOR_REPRESENTATIVE) or self.get_event().status == 'ARCHIVED':
            raise PermissionDenied
        # Skip organizer dispatch; sponsor role plus membership checked in the service.
        return CreateView.dispatch(self, request, *args, **kwargs)

    def get_success_url(self):
        return self.get_event().get_absolute_url()


class ChallengeReviewView(OrganizerMixin, View):
    def post(self, request, *args, **kwargs):
        challenge = get_object_or_404(Challenge, pk=kwargs['pk'], track__hackathon=self.get_event())
        try:
            services.review_challenge(actor=request.user, challenge=challenge, action=kwargs['action'])
            messages.success(request, _('Challenge mis à jour.'))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        return redirect(self.get_success_url())


class OrganizationCreateView(OrganizerMixin, CreateView):
    template_name = 'shared/form.html'

    def form_valid(self, form):
        with transaction.atomic():
            event = Hackathon.objects.select_for_update().get(pk=self.get_event().pk)
            require_organizer(self.request.user, event)
            self.object = form.save()
            services.record(event, self.request.user, 'Organisation créée', self.object, pk=self.object.pk)
        messages.success(self.request, _('Organisation créée. Ajoutez maintenant son partenariat.'))
        return redirect(self.get_success_url())


class RoleManageView(OrganizerMixin, FormView):
    template_name = 'shared/form.html'
    form_class = RoleForm
    extra_context = {'title': _('Affecter ou retirer un rôle dans ce hackathon')}

    def form_valid(self, form):
        try:
            set_role(actor=self.request.user, hackathon=self.get_event(), **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _('Affectation historisée.'))
        return redirect(self.get_success_url())


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'hackathons/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = Hackathon.objects.all()
        if not self.request.user.is_superuser:
            events = events.filter(role_assignments__user=self.request.user, role_assignments__role=Role.ORGANIZER,
                role_assignments__status='ACTIVE').distinct()
        now = timezone.now()
        context['rows'] = [{'event': event,
            'metrics': event.archive_metrics if event.status == 'ARCHIVED' else services.metrics(event),
            'current_phases': event.phases.filter(start__lte=now, end__gt=now) if event.status in ['PUBLISHED', 'ONGOING'] else [],
            'deadlines': event.phases.filter(end__gt=now, end__lte=now + timezone.timedelta(days=7)) if event.status in ['PUBLISHED', 'ONGOING'] else [],
            'errors': services.configuration_errors(event) if event.status != 'ARCHIVED' else [],
            'alerts': services.operational_alerts(event),
        } for event in events]
        context['active_count'] = events.filter(status__in=['PUBLISHED', 'ONGOING']).count()
        return context


class CompareView(LoginRequiredMixin, TemplateView):
    template_name = 'hackathons/compare.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = Hackathon.objects.all()
        if not self.request.user.is_superuser:
            events = events.filter(role_assignments__user=self.request.user, role_assignments__role=Role.ORGANIZER,
                role_assignments__status='ACTIVE').distinct()
        context['events'] = events
        context['rows'] = []
        for key in ('left', 'right'):
            value = self.request.GET.get(key)
            if value:
                if not value.isdecimal():
                    raise Http404
                event = get_object_or_404(events, pk=int(value))
                context['rows'].append({'event': event, 'metrics': event.archive_metrics if event.status == 'ARCHIVED' else services.metrics(event)})
        return context
