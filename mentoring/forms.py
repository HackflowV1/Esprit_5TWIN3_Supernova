from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.text import format_lazy

from accounts.models import Skill
from hackathons.models import Hackathon
from .models import MentorExpertise, MentorSlot, Workshop
from .services import mentor_open_hackathons

LEVELS = [(1, _('1 – Débutant')), (2, _('2 – Notions solides')), (3, _('3 – Intermédiaire')), (4, _('4 – Avancé')), (5, _('5 – Expert'))]
DATETIME = forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})


class MentorExpertiseForm(forms.ModelForm):
    level = forms.TypedChoiceField(label=_('Niveau'), choices=LEVELS, coerce=int, initial=3,
        help_text=_('Évaluez honnêtement votre niveau : il aide les équipes à trouver le bon mentor.'))

    class Meta:
        model = MentorExpertise
        fields = ('skill', 'level')
        labels = {'skill': _('Compétence')}

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
    """Create or edit a slot. Business rules live in mentoring.services; this form only collects the input."""

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
    """Create or edit a workshop. Business rules live in mentoring.services."""

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
