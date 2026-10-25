from decimal import Decimal
from django import forms
from django.forms import formset_factory
from .models import EvaluationCampaign, Prize
from . import services


class CriterionForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(label='Critère', max_length=150)
    weight = forms.DecimalField(label='Poids (%)', min_value=Decimal('0.01'), max_value=100, max_digits=5, decimal_places=2)
    max_score = forms.DecimalField(label='Note maximale', min_value=Decimal('0.01'), max_digits=7, decimal_places=2)
    display_order = forms.IntegerField(label='Ordre', min_value=0, max_value=32767, initial=0)


CriterionFormSet = formset_factory(CriterionForm, extra=1, can_delete=True, max_num=30, validate_max=True)


class CampaignForm(forms.ModelForm):
    class Meta:
        model = EvaluationCampaign
        fields = ['divergence_threshold', 'minimum_jurors']
        labels = {'divergence_threshold': 'Seuil de divergence (points /100)', 'minimum_jurors': 'Nombre minimum de jurés par projet'}


class AssignmentForm(forms.Form):
    submission = forms.ModelChoiceField(queryset=None, label='Soumission officielle')
    juror = forms.ModelChoiceField(queryset=None, label='Juré autorisé')

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['submission'].queryset = services.official_submissions(event)
        self.fields['juror'].queryset = services.jurors(event)


class EvaluationForm(forms.Form):
    comment = forms.CharField(label='Commentaire confidentiel', required=False, max_length=10000, widget=forms.Textarea(attrs={'rows': 4}))

    def __init__(self, *args, criteria, evaluation=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.criteria = list(criteria)
        scores = dict(evaluation.scores.values_list('criterion_id', 'score')) if evaluation else {}
        for c in self.criteria:
            self.fields[f'score_{c.pk}'] = forms.DecimalField(label=f'{c.name} — {c.weight} % · /{c.max_score}', required=False, min_value=0, max_value=c.max_score, max_digits=7, decimal_places=2, initial=scores.get(c.pk), widget=forms.NumberInput(attrs={'data-weight': str(c.weight), 'data-maximum': str(c.max_score), 'step': '.01'}))
        if evaluation:
            self.fields['comment'].initial = evaluation.comment
        self.order_fields([f'score_{c.pk}' for c in self.criteria] + ['comment'])

    def clean(self):
        data = super().clean()
        if self.data.get('action') == 'finalize':
            for c in self.criteria:
                if data.get(f'score_{c.pk}') is None:
                    self.add_error(f'score_{c.pk}', 'Note requise pour valider définitivement.')
        return data

    def scores(self):
        return {c.pk: self.cleaned_data.get(f'score_{c.pk}') for c in self.criteria}


class ReasonForm(forms.Form):
    reason = forms.CharField(label='Justification', max_length=2000, widget=forms.Textarea(attrs={'rows': 3}))


class PrizeForm(forms.ModelForm):
    class Meta:
        model = Prize
        fields = ['name', 'description', 'sponsorship']
        labels = {'name': 'Nom du prix', 'description': 'Description', 'sponsorship': 'Partenariat sponsor'}

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.hackathon = event
        self.fields['sponsorship'].queryset = event.sponsorships.filter(status='CONFIRMED')


class AwardForm(forms.Form):
    prize = forms.ModelChoiceField(queryset=None, label='Prix')
    submission = forms.ModelChoiceField(queryset=None, label='Gagnant')

    def __init__(self, *args, event, **kwargs):
        from projects.models import Submission
        super().__init__(*args, **kwargs)
        self.fields['prize'].queryset = event.prizes.filter(award__isnull=True)
        publication = event.result_publications.filter(published_at__isnull=False).first()
        ids = [r['submission_id'] for r in publication.ranking] if publication else []
        self.fields['submission'].queryset = Submission.objects.filter(pk__in=ids)
