from django import forms
from .models import Hackathon, Track, Challenge, EventPhase, SponsorOrganization, Sponsorship


class FrenchModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {'title': 'Titre', 'rules': 'Règlement', 'participation_conditions': 'Conditions de participation',
            'location': 'Lieu', 'start_date': 'Début de l’événement', 'end_date': 'Fin de l’événement',
            'registration_open': 'Ouverture des inscriptions', 'registration_close': 'Clôture des inscriptions',
            'submission_deadline': 'Date limite de soumission', 'capacity': 'Capacité maximale',
            'min_team_size': 'Taille minimale des équipes', 'max_team_size': 'Taille maximale des équipes',
            'name': 'Nom', 'active': 'Actif', 'kind': 'Type de phase', 'start': 'Début', 'end': 'Fin',
            'problem': 'Problématique', 'objectives': 'Objectifs', 'deliverables': 'Livrables attendus',
            'sponsorship': 'Partenariat sponsor', 'organization': 'Organisation', 'contribution_type': 'Type de contribution',
            'estimated_value': 'Valeur estimée', 'currency': 'Devise', 'status': 'Statut', 'prize_information': 'Informations pour les prix (M5)',
            'sector': 'Secteur', 'website': 'Site web', 'contact_name': 'Nom du contact', 'contact_email': 'Email du contact'}
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
