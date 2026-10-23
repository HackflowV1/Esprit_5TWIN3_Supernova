from django import forms

from accounts.models import AssignmentStatus, Role, Skill
from hackathons.models import Hackathon
from .models import MentorExpertise, MentorSlot
from .services import OPEN_STATUSES

LEVELS = [(1, '1 – Débutant'), (2, '2 – Notions solides'), (3, '3 – Intermédiaire'), (4, '4 – Avancé'), (5, '5 – Expert')]


class MentorExpertiseForm(forms.ModelForm):
    level = forms.TypedChoiceField(label='Niveau', choices=LEVELS, coerce=int, initial=3,
        help_text='Évaluez honnêtement votre niveau : il aide les équipes à trouver le bon mentor.')

    class Meta:
        model = MentorExpertise
        fields = ('skill', 'level')
        labels = {'skill': 'Compétence'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # The skill identifies the declaration: only its level can change.
            self.fields['skill'].disabled = True
        else:
            declared = MentorExpertise.objects.filter(user=self.instance.user).values('skill')
            self.fields['skill'].queryset = Skill.objects.exclude(pk__in=declared)
            self.fields['skill'].empty_label = 'Choisir une compétence'


class SlotForm(forms.Form):
    """Create or edit a slot. Business rules live in mentoring.services; this form only collects the input."""

    hackathon = forms.ModelChoiceField(label='Hackathon', queryset=Hackathon.objects.none(), empty_label='Choisir un hackathon')
    start = forms.DateTimeField(label='Début', widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
        help_text='Heure de Tunis.')
    end = forms.DateTimeField(label='Fin', widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
        help_text=f'Durée : de {MentorSlot.MIN_MINUTES} minutes à {MentorSlot.MAX_MINUTES // 60} heures, pendant l’événement.')

    def __init__(self, *args, user, slot=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hackathon'].queryset = Hackathon.objects.filter(
            role_assignments__user=user, role_assignments__role=Role.MENTOR,
            role_assignments__status=AssignmentStatus.ACTIVE, status__in=OPEN_STATUSES).distinct()
        if slot is not None:
            # A slot never moves to another hackathon.
            self.fields['hackathon'].disabled = True
            self.initial = {'hackathon': slot.hackathon, 'start': slot.start, 'end': slot.end}
