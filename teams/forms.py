from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Team, TeamSkillNeed, Registration


class RegistrationForm(forms.Form):
    accept_conditions = forms.BooleanField(label=_('J’accepte le règlement et les conditions de participation.'), help_text=_('Vérifiez que vous remplissez les conditions indiquées par l’organisateur.'))


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'description', 'recruiting']
        help_texts = {'description':_('Pour les suggestions IA par projet, rédigez cette description en anglais.')}
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


class SkillDescriptionForm(forms.Form):
    text = forms.CharField(label=_('Le travail technique prévu'),min_length=15,max_length=1200,
        widget=forms.Textarea(attrs={'rows':4,'placeholder':_('Décrivez ce que vous allez construire et les outils envisagés…')}),
        help_text=_('Décrivez le travail en anglais : le modèle léger est optimisé pour cette langue. Confirmez ensuite les suggestions utiles.'))


class SuggestedNeedForm(forms.Form):
    selected = forms.BooleanField(required=False,label=_('Ajouter ce besoin'))
    skill = forms.ModelChoiceField(queryset=None,widget=forms.HiddenInput)
    level = forms.TypedChoiceField(label=_('Niveau souhaité'),coerce=int,required=False,empty_value=None,choices=[('',_('Choisir'))]+[(i,str(i)+'/5') for i in range(1,6)])
    priority = forms.TypedChoiceField(label=_('Priorité'),coerce=int,required=False,empty_value=None,choices=[('',_('Choisir')),(1,_('Utile')),(2,_('Importante')),(3,_('Essentielle'))])

    def __init__(self,*args,allowed_skills,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['skill'].queryset = allowed_skills

    @property
    def skill_label(self):
        value = str(self['skill'].value() or '')
        return self.fields['skill'].queryset.filter(pk=int(value)).first() if value.isdigit() else _('Compétence')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('selected'):
            for name in ('level','priority'):
                if not cleaned.get(name):
                    self.add_error(name,_('Choisissez une valeur pour ce besoin.'))
        return cleaned
