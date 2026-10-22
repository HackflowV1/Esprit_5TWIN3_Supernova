from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from .models import User, Profile, UserSkill, Role, AssignmentStatus


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Cet email est déjà utilisé.')
        return email

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            Profile.objects.get_or_create(user=user)
        return user


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(label='Prénom', max_length=150, required=False)
    last_name = forms.CharField(label='Nom', max_length=150, required=False)
    email = forms.EmailField()

    class Meta:
        model = Profile
        fields = ('first_name', 'last_name', 'email', 'biography', 'university', 'interests', 'avatar')
        labels = {'biography': 'Biographie', 'university': 'Établissement / université', 'interests': 'Centres d’intérêt'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('first_name', 'last_name', 'email'):
            self.fields[name].initial = getattr(self.instance.user, name)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.user_id).exists():
            raise forms.ValidationError('Cet email est déjà utilisé.')
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
        labels = {'skill': 'Compétence', 'level': 'Niveau (1–5)', 'experience': 'Expérience'}


class RoleForm(forms.Form):
    user = forms.ModelChoiceField(label='Utilisateur', queryset=User.objects.filter(is_active=True))
    role = forms.ChoiceField(label='Rôle', choices=Role.choices)
    status = forms.ChoiceField(label='Statut', choices=AssignmentStatus.choices)
