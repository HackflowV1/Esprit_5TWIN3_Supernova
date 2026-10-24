from django import forms
from django.utils.translation import gettext_lazy as _
from hackathons.models import Challenge
from .models import Project, Milestone, Deliverable


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['challenge', 'title', 'problem', 'solution', 'stack', 'pitch', 'status']

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.team = team
        self.fields['challenge'].queryset = Challenge.objects.filter(track__hackathon=team.hackathon, track__active=True, status='PUBLISHED')


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ['title', 'due_at', 'progress']
        widgets = {'due_at': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})}
        help_texts = {'progress': _('L’état suit automatiquement la progression : 0 % à faire, 1–99 % en cours, 100 % terminé.')}


class DeliverableForm(forms.Form):
    kind = forms.ChoiceField(label=_('Type'), choices=Deliverable.Kind.choices)
    url = forms.URLField(label=_('Lien HTTPS'), required=False, max_length=1000)
    file = forms.FileField(label=_('Fichier'), required=False, help_text=_('PDF, ZIP ou MP4, 20 Mo maximum. Les fichiers restent privés jusqu’à publication.'))
    commit = forms.CharField(label=_('Commit Git complet'), max_length=64, required=False, help_text=_('Obligatoire pour un dépôt de code.'))


class SubmitForm(forms.Form):
    confirm_requirements = forms.BooleanField(label=_('Je confirme que cette version respecte toutes les exigences du challenge et que ses liens sont accessibles au jury.'))


class ReopenForm(forms.Form):
    reason = forms.CharField(label=_('Justification'), widget=forms.Textarea, max_length=2000)
    until = forms.DateTimeField(label=_('Nouvelle limite'), widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
