from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import IntegrityError, transaction
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, UpdateView, TemplateView, DeleteView
from .forms import SignupForm, ProfileForm, UserSkillForm
from .models import Profile, UserSkill


class SignupView(SuccessMessageMixin, CreateView):
    form_class = SignupForm
    template_name = 'accounts/auth.html'
    success_url = reverse_lazy('accounts:profile')
    success_message = _('Votre compte a été créé.')
    extra_context = {'title': _('Créer mon compte'), 'button_label': _('Créer mon compte')}

    def return_url(self):
        target = self.request.POST.get('next') or self.request.GET.get('next', '')
        return target if url_has_allowed_host_and_scheme(target, allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure()) else ''

    def get_success_url(self):
        return self.return_url() or super().get_success_url()

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), 'next': self.return_url()}

    def form_valid(self, form):
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except IntegrityError:
            form.add_error(None, _('Identifiant ou email déjà utilisé.'))
            return self.form_invalid(form)
        login(self.request, self.object)
        return response


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile'], _ = Profile.objects.get_or_create(user=self.request.user)
        context['skills'] = self.request.user.user_skills.select_related('skill')
        context['assignments'] = self.request.user.role_assignments.select_related('hackathon')
        context['memberships'] = self.request.user.sponsor_memberships.select_related('organization')
        return context


class ProfileUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    form_class = ProfileForm
    template_name = 'accounts/profile_form.html'
    success_url = reverse_lazy('accounts:profile')
    success_message = _('Profil mis à jour.')
    extra_context = {'title': _('Modifier mon profil')}

    def get_object(self, queryset=None):
        return Profile.objects.get_or_create(user=self.request.user)[0]

    def form_valid(self, form):
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except IntegrityError:
            form.add_error(None, _('Cet email est déjà utilisé.'))
            return self.form_invalid(form)


class SkillCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    form_class = UserSkillForm
    template_name = 'accounts/profile_form.html'
    success_url = reverse_lazy('accounts:profile')
    success_message = _('Compétence ajoutée.')
    extra_context = {'title': _('Ajouter une compétence')}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = UserSkill(user=self.request.user)
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except IntegrityError:
            form.add_error(None, _('Cette compétence existe déjà sur votre profil.'))
            return self.form_invalid(form)


class SkillUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    form_class = UserSkillForm
    template_name = 'accounts/profile_form.html'
    success_url = reverse_lazy('accounts:profile')
    success_message = _('Compétence modifiée.')

    def get_queryset(self):
        return UserSkill.objects.filter(user=self.request.user)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                return super().form_valid(form)
        except IntegrityError:
            form.add_error(None, _('Cette compétence existe déjà sur votre profil.'))
            return self.form_invalid(form)


class SkillDeleteView(LoginRequiredMixin, DeleteView):
    template_name = 'accounts/profile_delete.html'
    success_url = reverse_lazy('accounts:profile')

    def get_queryset(self):
        return UserSkill.objects.filter(user=self.request.user)
