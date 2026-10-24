"""Local demo data for M4: a dedicated edition that is *ongoing today*, with two complete teams,
mentors with expertises and slots, and help requests. Development only; safe to run again.

It reuses the real M2 services (registration, team, invitation, acceptance) and the M4 services,
so the data respects the rules. It never moves the dates of an existing edition: it creates its own.
"""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, Skill, User
from accounts.services import set_role
from hackathons.models import Challenge, EventPhase, Hackathon, Track
from hackathons.services import create_hackathon, phase_is_open, review_challenge, save_resource, transition
from mentoring import services
from mentoring.models import MentorExpertise, MentorSlot, SupportRequest
from teams import services as team_services
from teams.models import Decision, Registration, Team

SLUG = 'mentoring-lab-2026'
REQUIRED = ('organisatrice', 'mentor.django', 'mentor.front', 'mentor.data', 'ahmed', 'mariem', 'sami', 'ines')
EXPERTISES = {
    'mentor.django': [('Django', 5, 'Je réponds sur Django, DRF, les tests et PostgreSQL.'), ('Python', 5, '')],
    'mentor.front': [('React', 5, 'Composants, état et accessibilité.'), ('UI/UX', 4, 'Maquettes et parcours utilisateur.')],
    'mentor.data': [('Machine Learning', 5, 'Choisir un modèle et l’évaluer honnêtement.'), ('Data Science', 5, '')],
}


class Command(BaseCommand):
    help = 'Create a demo edition with two complete teams, mentors, slots and help requests. Run seed_demo first.'

    def add_arguments(self, parser):
        parser.add_argument('--user', help='Existing username that becomes organizer and mentor of the demo edition.')
        parser.add_argument('--force', action='store_true', help='Allow the command when DEBUG is off.')

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError('Refus : DEBUG est désactivé. Cette commande est réservée au développement (--force pour passer outre).')
        users = {u.username: u for u in User.objects.filter(username__in=REQUIRED)}
        missing = [name for name in REQUIRED if name not in users]
        if missing:
            raise CommandError(f'Comptes de démonstration absents ({", ".join(missing)}) : lancez d’abord seed_demo.')
        own = User.objects.filter(username=options['user']).first() if options['user'] else None
        if options['user'] and own is None:
            raise CommandError(f'Utilisateur introuvable : {options["user"]}')
        with transaction.atomic():
            event = self.event(users['organisatrice'])
            self.roles(event, users, own)
            if not phase_is_open(event, EventPhase.Kind.DEVELOPMENT):
                self.stdout.write(self.style.WARNING(
                    'La phase de développement de cette édition de démonstration est terminée : équipes et demandes non recréées.'))
            else:
                nova = self.team(event, users['ahmed'], users['mariem'], 'Nova Live',
                    'Un assistant d’orientation pour les étudiants. Backend Django en cours, interface à terminer.')
                horizon = self.team(event, users['sami'], users['ines'], 'Horizon Live',
                    'Une application mobile qui relie commerces et associations contre le gaspillage.')
                self.expertises()
                self.slots(event, users)
                self.requests(nova, horizon, users)
        self.report(event, own)

    # ------------------------------------------------------------------ data
    def event(self, organizer):
        existing = Hackathon.objects.filter(slug=SLUG).first()
        if existing:
            return existing
        now = timezone.now().replace(second=0, microsecond=0)
        start, end = now - timedelta(hours=2), now + timedelta(days=3)
        deadline = now + timedelta(days=2)
        event = create_hackathon(actor=organizer, event=Hackathon(
            title='Mentoring Lab 2026', slug=SLUG, format=Hackathon.Format.HYBRID, location='ESPRIT, Ariana',
            description='Une édition de démonstration, ouverte aujourd’hui : équipes complètes, mentors et demandes d’aide.',
            rules='Équipes de 2 à 5 personnes. Respect du code de conduite.',
            participation_conditions='Édition de démonstration.',
            start_date=start, end_date=end, registration_open=now - timedelta(days=3), registration_close=now + timedelta(days=2),
            submission_deadline=deadline, capacity=60, min_team_size=2, max_team_size=5))
        track = save_resource(actor=organizer, resource=Track(hackathon=event, name='Assistance étudiante', description='Des outils utiles aux étudiants.'))
        challenge = save_resource(actor=organizer, resource=Challenge(track=track, title='Un assistant pour réussir ses études',
            problem='Aider les étudiants à s’organiser et à progresser.', objectives='Un prototype utilisable.',
            deliverables='Code, démo et diaporama.', proposed_by=organizer))
        review_challenge(actor=organizer, challenge=challenge, action='approve')
        review_challenge(actor=organizer, challenge=challenge, action='publish')
        phases = [('REGISTRATION', event.registration_open, event.registration_close),
            ('TEAM_FORMATION', now - timedelta(days=2), now + timedelta(days=2)),
            ('DEVELOPMENT', start, deadline), ('SUBMISSION', start + timedelta(hours=1), deadline),
            ('EVALUATION', deadline, deadline + timedelta(hours=12)), ('RESULTS', deadline + timedelta(hours=12), end)]
        for kind, begin, finish in phases:
            save_resource(actor=organizer, resource=EventPhase(hackathon=event, kind=kind, start=begin, end=finish))
        transition(actor=organizer, event=event, target=Hackathon.Status.PUBLISHED)
        return transition(actor=organizer, event=event, target=Hackathon.Status.ONGOING)

    def roles(self, event, users, own):
        organizer = users['organisatrice']
        for name in ('mentor.django', 'mentor.front', 'mentor.data'):
            set_role(actor=organizer, user=users[name], hackathon=event, role=Role.MENTOR)
        if own:
            set_role(actor=organizer, user=own, hackathon=event, role=Role.ORGANIZER)
            set_role(actor=organizer, user=own, hackathon=event, role=Role.MENTOR)

    def team(self, event, captain, member, name, description):
        existing = Team.objects.filter(hackathon=event, name__iexact=name).first()
        if existing:
            return existing
        team_services.register(actor=captain, event=event, accept_conditions=True)
        team = team_services.create_team(actor=captain, event=event, name=name, description=description)
        team_services.register(actor=member, event=event, accept_conditions=True)
        invitation = team_services.recruit(actor=captain, team=team, registration=Registration.objects.get(user=member, hackathon=event),
            message='On travaille ensemble ?')
        team_services.decide(actor=member, record=invitation, decision=Decision.ACCEPTED)
        return team

    def expertises(self):
        for username, rows in EXPERTISES.items():
            user = User.objects.get(username=username)
            for skill_name, level, description in rows:
                MentorExpertise.objects.get_or_create(user=user, skill=Skill.objects.get(name=skill_name),
                    defaults={'level': level, 'description': description})

    def slots(self, event, users):
        now = timezone.now().replace(second=0, microsecond=0)
        first = now + timedelta(hours=1)
        first += timedelta(minutes=(30 - first.minute % 30) % 30)
        plan = {'mentor.django': [timedelta(0), timedelta(hours=1), timedelta(days=1)],
                'mentor.front': [timedelta(minutes=30), timedelta(hours=2)], 'mentor.data': [timedelta(hours=1)]}
        for username, offsets in plan.items():
            mentor = users[username]
            if MentorSlot.objects.published().filter(mentor=mentor, hackathon=event, end__gt=now).exists():
                continue
            for offset in offsets:
                try:
                    services.create_slot(actor=mentor, hackathon=event, start=first + offset, end=first + offset + timedelta(minutes=45))
                except ValidationError:
                    pass  # a slot that no longer fits the calendar is simply skipped

    def requests(self, nova, horizon, users):
        django = Skill.objects.get(name='Django')
        if not SupportRequest.objects.filter(team=nova).exists():
            services.open_request(actor=users['ahmed'], team=nova, subject='Erreur 500 sur notre API Django',
                description='Le serializer plante dès qu’on envoie un champ vide. Voici la trace : KeyError: "title".',
                skill=django, priority=SupportRequest.Priority.HIGH)
        if not SupportRequest.objects.filter(team=horizon).exists():
            services.open_request(actor=users['sami'], team=horizon, subject='Déploiement bloqué',
                description='Impossible de lancer le serveur en production : la migration échoue.',
                skill=django, priority=SupportRequest.Priority.CRITICAL)
            services.open_request(actor=users['ines'], team=horizon, subject='Quelle navigation pour l’application mobile ?',
                description='Nous hésitons entre onglets et menu latéral pour les écrans principaux.',
                skill=Skill.objects.get(name='Mobile'), priority=SupportRequest.Priority.LOW)

    # ---------------------------------------------------------------- output
    def report(self, event, own):
        write = self.stdout.write
        write(self.style.SUCCESS(f'Édition de démonstration prête : {event.title} (/hackathons/{event.slug}/)'))
        write('')
        write('Mot de passe de tous les comptes de démonstration : Demo-Hack#2026')
        write('')
        write('  ahmed, mariem        équipe complète « Nova Live » (ahmed est capitaine)')
        write('  sami, ines           équipe complète « Horizon Live » (sami est capitaine)')
        write('  mentor.django        mentor Django : expertises et créneaux publiés')
        write('  mentor.front         mentor React / UI-UX    mentor.data   mentor Data / ML')
        write('  organisatrice        organisatrice de l’édition (pilotage de l’assistance)')
        if own:
            write(f'  {own.username:<20} organisateur et mentor de l’édition (vos droits ont été ajoutés)')
        write('')
        write('À essayer : connectez-vous avec « ahmed », ouvrez « Mentorat » dans le menu, puis « Mes demandes ».')
