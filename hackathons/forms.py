from django.utils.translation import gettext_lazy as _
from django import forms
from .models import Hackathon, Track, Challenge, EventPhase, SponsorOrganization, Sponsorship


class FrenchModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {'title': _('Titre'), 'rules': _('Règlement'), 'participation_conditions': _('Conditions de participation'),
            'description': _('Description'), 'image': _('Image'), 'slug': _('Identifiant dans l’URL'),
            'format': _('Format'), 'track': _('Track'), 'logo': _('Logo'),
            'location': _('Lieu'), 'start_date': _('Début de l’événement'), 'end_date': _('Fin de l’événement'),
            'registration_open': _('Ouverture des inscriptions'), 'registration_close': _('Clôture des inscriptions'),
            'submission_deadline': _('Date limite de soumission'), 'capacity': _('Capacité maximale'),
            'min_team_size': _('Taille minimale des équipes'), 'max_team_size': _('Taille maximale des équipes'),
            'name': _('Nom'), 'active': _('Actif'), 'kind': _('Type de phase'), 'start': _('Début'), 'end': _('Fin'),
            'problem': _('Problématique'), 'objectives': _('Objectifs'), 'deliverables': _('Livrables attendus'),
            'sponsorship': _('Partenariat sponsor'), 'organization': _('Organisation'), 'contribution_type': _('Type de contribution'),
            'estimated_value': _('Valeur estimée'), 'currency': _('Devise'), 'status': _('Statut'), 'prize_information': _('Informations pour les prix (M5)'),
            'sector': _('Secteur'), 'website': _('Site web'), 'contact_name': _('Nom du contact'), 'contact_email': _('Email du contact')}
        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            if isinstance(field, forms.DateTimeField):
                field.widget = forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})


class HackathonForm(FrenchModelForm):
    class Meta:
        model = Hackathon
        fields = ('title', 'slug', 'description', 'rules', 'participation_conditions', 'image', 'location', 'format',
            'start_date', 'end_date', 'registration_open', 'registration_close', 'submission_deadline',
            'capacity', 'min_team_size', 'max_team_size')


class TrackForm(FrenchModelForm):
    class Meta:
        model = Track
        fields = ('name', 'description', 'active')


class PhaseForm(FrenchModelForm):
    class Meta:
        model = EventPhase
        fields = ('kind', 'start', 'end')


class ChallengeForm(FrenchModelForm):
    class Meta:
        model = Challenge
        fields = ('track', 'title', 'problem', 'objectives', 'deliverables', 'participation_conditions', 'sponsorship')

    def __init__(self, *args, event, user=None, sponsor=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['track'].queryset = event.tracks.filter(active=True)
        partnerships = event.sponsorships.filter(status=Sponsorship.Status.CONFIRMED)
        if sponsor:
            partnerships = partnerships.filter(organization__memberships__user=user,
                organization__memberships__status='ACTIVE', organization__memberships__can_propose_challenges=True)
            self.fields['sponsorship'].required = True
        self.fields['sponsorship'].queryset = partnerships.distinct()


class ChallengeSuggestionForm(forms.Form):
    track = forms.ModelChoiceField(queryset=Track.objects.none(), label=_('Track'))
    idea = forms.CharField(label=_('Idée ou thème'), max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3}), help_text=_('Requis uniquement pour demander une suggestion.'))
    audience = forms.CharField(label=_('Public visé'), max_length=150, required=False)
    duration = forms.CharField(label=_('Durée envisagée'), max_length=100, required=False,
        help_text=_('Par exemple : 24 heures. Cette indication ne modifie aucune date.'))

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['track'].queryset = event.tracks.filter(active=True)


class GeneratedChallengeForm(forms.Form):
    """Text-only suggestions: no model status, dates or permissions can enter here."""
    title = forms.CharField(max_length=200)
    problem = forms.CharField(max_length=4000)
    objectives = forms.CharField(max_length=4000)
    deliverables = forms.CharField(max_length=4000)


class OrganizationForm(FrenchModelForm):
    class Meta:
        model = SponsorOrganization
        fields = ('name', 'logo', 'sector', 'website', 'description', 'contact_name', 'contact_email')


class SponsorshipForm(FrenchModelForm):
    class Meta:
        model = Sponsorship
        fields = ('organization', 'contribution_type', 'estimated_value', 'currency', 'status', 'prize_information')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['organization'].disabled = True
