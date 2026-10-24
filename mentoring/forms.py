from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy

from accounts.models import Skill
from hackathons.models import Hackathon
from teams.models import Team
from .models import MentorExpertise, MentorSlot, SupportRequest, Workshop
from .services import mentor_open_hackathons, requestable_teams

LEVELS = [(1, _('1 – Débutant')), (2, _('2 – Notions solides')), (3, _('3 – Intermédiaire')), (4, _('4 – Avancé')), (5, _('5 – Expert'))]
DATETIME = forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})


class MentorExpertiseForm(forms.ModelForm):
    level = forms.TypedChoiceField(label=_('Niveau'), choices=LEVELS, coerce=int, initial=3,
        help_text=_('Évaluez honnêtement votre niveau : il aide les équipes à trouver le bon mentor.'))

    class Meta:
        model = MentorExpertise
        fields = ('skill', 'level', 'description')
        labels = {'skill': _('Compétence'), 'description': _('Présentation')}
        help_texts = {'description': _('Comment pouvez-vous aider les équipes ? (500 caractères maximum)')}
        widgets = {'description': forms.Textarea(attrs={'rows': 3, 'maxlength': 500})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # The skill identifies the declaration: only its level can change.
            self.fields['skill'].disabled = True
        else:
            declared = MentorExpertise.objects.filter(user=self.instance.user).values('skill')
            self.fields['skill'].queryset = Skill.objects.exclude(pk__in=declared)
            self.fields['skill'].empty_label = _('Choisir une compétence')


class SlotForm(forms.Form):

    hackathon = forms.ModelChoiceField(label=_('Hackathon'), queryset=Hackathon.objects.none(), empty_label=_('Choisir un hackathon'))
    start = forms.DateTimeField(label=_('Début'), widget=DATETIME, help_text=_('Heure de Tunis.'))
    end = forms.DateTimeField(label=_('Fin'), widget=DATETIME,
        help_text=format_lazy(_('Durée : de {min} minutes à {max} heures, pendant l’événement.'),
            min=MentorSlot.MIN_MINUTES, max=MentorSlot.MAX_MINUTES // 60))

    def __init__(self, *args, user, slot=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hackathon'].queryset = mentor_open_hackathons(user)
        if slot is not None:
            # A slot never moves to another hackathon.
            self.fields['hackathon'].disabled = True
            self.initial = {'hackathon': slot.hackathon, 'start': slot.start, 'end': slot.end}


class WorkshopForm(forms.Form):

    hackathon = forms.ModelChoiceField(label=_('Hackathon'), queryset=Hackathon.objects.none(), empty_label=_('Choisir un hackathon'))
    title = forms.CharField(label=_('Thème de l’atelier'), max_length=200)
    description = forms.CharField(label=_('Description'), required=False, widget=forms.Textarea(attrs={'rows': 4}),
        help_text=_('Contenu, prérequis, matériel à apporter…'))
    capacity = forms.IntegerField(label=_('Nombre de places'), min_value=1, max_value=Workshop.MAX_CAPACITY, initial=20)
    start = forms.DateTimeField(label=_('Début'), widget=DATETIME, help_text=_('Heure de Tunis.'))
    end = forms.DateTimeField(label=_('Fin'), widget=DATETIME,
        help_text=format_lazy(_('Durée : de {min} minutes à {max} heures, pendant l’événement.'),
            min=Workshop.MIN_MINUTES, max=Workshop.MAX_MINUTES // 60))
    location = forms.CharField(label=_('Salle'), max_length=200, required=False, help_text=_('Salle ou lieu, si l’atelier est sur place.'))
    url = forms.URLField(label=_('Lien en ligne'), required=False, help_text=_('Indiquez une salle, un lien, ou les deux.'))

    def __init__(self, *args, user, workshop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hackathon'].queryset = mentor_open_hackathons(user)
        if workshop is not None:
            # A workshop never moves to another hackathon.
            self.fields['hackathon'].disabled = True
            self.initial = {name: getattr(workshop, name) for name in
                ('hackathon', 'title', 'description', 'capacity', 'start', 'end', 'location', 'url')}


class SupportRequestForm(forms.Form):
    """Open a help request. Authorization and the open development phase are checked by the service."""

    team = forms.ModelChoiceField(label=_('Équipe'), queryset=Team.objects.none(), empty_label=None)
    subject = forms.CharField(label=_('Sujet'), max_length=200, help_text=_('Résumez le blocage en une phrase.'))
    description = forms.CharField(label=_('Décrivez le blocage'), widget=forms.Textarea(attrs={'rows': 6}),
        help_text=_('Ce que vous avez essayé, le message d’erreur, ce que vous attendez…'))
    skill = forms.ModelChoiceField(label=_('Compétence concernée'), queryset=Skill.objects.all(), required=False,
        empty_label=_('Je ne sais pas / autre'), help_text=_('Elle aide à trouver le bon mentor.'))
    priority = forms.ChoiceField(label=_('Priorité'), choices=SupportRequest.Priority.choices,
        initial=SupportRequest.Priority.NORMAL,
        help_text=_('Critique : tout est bloqué. Élevée : vous avancez très lentement. Normale : une question précise.'))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['team'].queryset = Team.objects.filter(pk__in=[team.pk for team in requestable_teams(user)]).select_related('hackathon')
        self.fields['team'].label_from_instance = lambda team: f'{team.name} — {team.hackathon.title}'
