from django import forms
from django.utils.translation import gettext_lazy as _
from hackathons.models import Challenge
from .models import Project, Milestone, Deliverable
from .validators import validate_commit, validate_link


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
    url = forms.URLField(label=_('Lien HTTPS'), required=False, max_length=1000, validators=[validate_link],
        widget=forms.URLInput(attrs={'placeholder': 'https://github.com/username/project'}))
    file = forms.FileField(label=_('Fichier'), required=False, help_text=_('PDF, ZIP ou MP4, 20 Mo maximum. Les fichiers restent privés jusqu’à publication.'),
        widget=forms.FileInput(attrs={'accept': '.pdf,.zip,.mp4'}))
    commit = forms.CharField(label=_('Commit Git complet'), max_length=64, required=False, validators=[validate_commit],
        help_text=_('Sur GitHub, ouvrez le commit et copiez le SHA complet depuis son URL ou le bouton de copie. Le code court de 7 caractères ne suffit pas.'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kind = self.data.get(self.add_prefix('kind')) if self.is_bound else self.initial.get('kind', Deliverable.Kind.REPOSITORY)
        repository = kind == Deliverable.Kind.REPOSITORY
        self.fields['url'].required = repository
        self.fields['commit'].required = repository


class SubmitForm(forms.Form):
    confirm_requirements = forms.BooleanField(label=_('Je confirme que cette version respecte toutes les exigences du challenge et que ses liens sont accessibles au jury.'))


class ReopenForm(forms.Form):
    reason = forms.CharField(label=_('Justification'), widget=forms.Textarea, max_length=2000)
    until = forms.DateTimeField(label=_('Nouvelle limite'), widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
