from django import forms

from accounts.models import Skill
from .models import MentorExpertise

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
