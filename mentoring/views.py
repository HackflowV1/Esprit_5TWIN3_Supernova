from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, TemplateView, UpdateView

from accounts.models import AssignmentStatus, Role
from . import services
from .forms import MentorExpertiseForm, SlotForm, WorkshopForm
from .models import MentorExpertise, MentorSlot, Workshop
from .permissions import MentorRequiredMixin, is_mentor


def group_by_day(items, attr='start'):
    """Group already ordered objects by local calendar day: [{'day': date, 'items': [...]}]."""
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
        own = MentorSlot.objects.filter(mentor=self.request.user).select_related('hackathon')
        upcoming = list(own.filter(end__gt=now).exclude(status=MentorSlot.Status.CANCELLED).order_by('start'))
        context['days'] = [{'day': g['day'], 'slots': g['items']} for g in group_by_day(upcoming)]
        context['upcoming_count'] = len(upcoming)
        context['history'] = own.filter(Q(end__lte=now) | Q(status=MentorSlot.Status.CANCELLED)).order_by('-start')[:15]
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
class WorkshopListView(LoginRequiredMixin, TemplateView):
    """Workshops of the hackathons in which the user holds a role; trainers also see their own."""
    template_name = 'mentoring/workshop_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user, now = self.request.user, timezone.now()
        upcoming = list(services.visible_workshops(user).filter(
            status=Workshop.Status.PUBLISHED, end__gt=now).order_by('start'))
        context['days'] = [{'day': g['day'], 'workshops': g['items']} for g in group_by_day(upcoming)]
        context['upcoming_count'] = len(upcoming)
        context['is_trainer'] = is_mentor(user)
        context['mine'] = Workshop.objects.filter(trainer=user).select_related('hackathon').order_by('-start')[:20]
        context['can_create'] = services.mentor_open_hackathons(user).exists()
        context['now'] = now
        return context


class WorkshopDetailView(LoginRequiredMixin, DetailView):
    template_name = 'mentoring/workshop_detail.html'
    context_object_name = 'workshop'

    def get_queryset(self):
        return services.visible_workshops(self.request.user)  # other hackathons: 404, existence stays private

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workshop = self.object
        context['can_edit'] = (workshop.trainer_id == self.request.user.pk
            and workshop.status == Workshop.Status.PUBLISHED and workshop.start > timezone.now())
        return context


class WorkshopFormMixin(MentorRequiredMixin, FormView):
    form_class = WorkshopForm
    template_name = 'shared/form.html'

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
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        except PermissionDenied as exc:
            form.add_error(None, str(exc) or _('Action non autorisée.'))
            return self.form_invalid(form)
        messages.success(self.request, self.success_message)
        return redirect(self.workshop.get_absolute_url())

    def workshop_fields(self, form):
        data = form.cleaned_data
        return {name: data[name] for name in ('title', 'description', 'capacity', 'start', 'end', 'location', 'url')}


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
            self._workshop = get_object_or_404(Workshop, pk=self.kwargs['pk'], trainer=self.request.user)
        return self._workshop

    def run(self, form):
        return services.update_workshop(actor=self.request.user, workshop=self.get_workshop(), **self.workshop_fields(form))


class WorkshopCancelView(MentorRequiredMixin, View):
    template_name = 'mentoring/workshop_cancel.html'

    def get_workshop(self):
        return get_object_or_404(Workshop, pk=self.kwargs['pk'], trainer=self.request.user)

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {'workshop': self.get_workshop()})

    def post(self, request, *args, **kwargs):
        workshop = self.get_workshop()
        try:
            services.cancel_workshop(actor=request.user, workshop=workshop)
            messages.success(request, _('Atelier annulé.'))
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        return redirect(reverse('mentoring:workshop-list'))
