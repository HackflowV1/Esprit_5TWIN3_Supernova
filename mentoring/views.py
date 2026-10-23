from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from accounts.models import AssignmentStatus, Role
from .forms import MentorExpertiseForm
from .models import MentorExpertise
from .permissions import MentorRequiredMixin


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
    success_message = 'Expertise ajoutée.'
    extra_context = {'title': 'Ajouter une expertise', 'button_label': 'Ajouter'}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = MentorExpertise(user=self.request.user)
        return kwargs


class ExpertiseUpdateView(OwnExpertiseMixin, SuccessMessageMixin, UpdateView):
    form_class = MentorExpertiseForm
    template_name = 'shared/form.html'
    success_message = 'Niveau mis à jour.'
    extra_context = {'title': 'Modifier mon niveau'}


class ExpertiseDeleteView(OwnExpertiseMixin, DeleteView):
    template_name = 'shared/confirm_delete.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Expertise retirée.')
        return response
