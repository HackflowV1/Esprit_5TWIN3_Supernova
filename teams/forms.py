from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Team, TeamSkillNeed, Registration


class RegistrationForm(forms.Form):
    accept_conditions = forms.BooleanField(label=_('J’accepte le règlement et les conditions de participation.'), help_text=_('Vérifiez que vous remplissez les conditions indiquées par l’organisateur.'))


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'description', 'recruiting']
        widgets = {'description': forms.Textarea(attrs={'rows': 4, 'placeholder': _('Une idée, des envies, les profils que vous cherchez…')})}


class MessageForm(forms.Form):
    message = forms.CharField(label=_('Message'), required=False, max_length=1000, widget=forms.Textarea(attrs={'rows': 3}), help_text=_('Présentez votre motivation ou votre idée en quelques mots.'))


class InvitationForm(MessageForm):
    registration = forms.ModelChoiceField(queryset=Registration.objects.none(), label=_('Participant à inviter'))

    def __init__(self, *args, candidates, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['registration'].queryset = candidates
        self.fields['registration'].label_from_instance = lambda reg: reg.user.get_full_name() or reg.user.username


class NeedForm(forms.ModelForm):
    level = forms.TypedChoiceField(label=_('Niveau souhaité'), coerce=int, choices=[(1, _('1 · Découverte')), (2, _('2 · Bases')), (3, _('3 · Autonome')), (4, _('4 · Avancé')), (5, _('5 · Expert'))])
    class Meta:
        model = TeamSkillNeed
        fields = ['skill', 'level', 'priority']
        labels = {'skill': _('Compétence recherchée')}
