from django.utils.translation import gettext_lazy as _
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from .models import User, Profile, UserSkill, Role, AssignmentStatus


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, value in (('username', 'username'), ('first_name', 'given-name'), ('last_name', 'family-name'), ('email', 'email')):
            self.fields[name].widget.attrs['autocomplete'] = value
        # Rules are reported by the server under each field after submission; validators are unchanged.
        for name in ('username', 'password1', 'password2'):
            self.fields[name].help_text = ''
        self.fields['password1'].widget.attrs['placeholder'] = _('8 caractères minimum')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_('Cet email est déjà utilisé.'))
        return email

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            Profile.objects.get_or_create(user=user)
        return user


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(label=_('Prénom'), max_length=150, required=False)
    last_name = forms.CharField(label=_('Nom'), max_length=150, required=False)
    email = forms.EmailField()

    class Meta:
        model = Profile
        fields = ('first_name', 'last_name', 'email', 'biography', 'university', 'interests', 'avatar')
        labels = {'biography': _('Biographie'), 'university': _('Établissement / université'), 'interests': _('Centres d’intérêt'), 'avatar': _('Photo de profil')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('first_name', 'last_name', 'email'):
            self.fields[name].initial = getattr(self.instance.user, name)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.user_id).exists():
            raise forms.ValidationError(_('Cet email est déjà utilisé.'))
        return email

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=False)
        for name in ('first_name', 'last_name', 'email'):
            setattr(profile.user, name, self.cleaned_data[name])
        if commit:
            profile.user.full_clean()
            profile.user.save()
            profile.save()
        return profile


class UserSkillForm(forms.ModelForm):
    class Meta:
        model = UserSkill
        fields = ('skill', 'level', 'experience')
        labels = {'skill': _('Compétence'), 'level': _('Niveau (1–5)'), 'experience': _('Expérience')}


class RoleForm(forms.Form):
    user = forms.ModelChoiceField(label=_('Utilisateur'), queryset=User.objects.filter(is_active=True))
    role = forms.ChoiceField(label=_('Rôle'), choices=Role.choices)
    status = forms.ChoiceField(label=_('Statut'), choices=AssignmentStatus.choices)
