"""Populate hackflow_db with a coherent demo dataset (development / jury demonstration only)."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile, Role, Skill, SponsorMembership, User, UserSkill
from accounts.services import set_role
from hackathons.models import Challenge, EventPhase, Hackathon, SponsorOrganization, Sponsorship, Track
from hackathons.services import create_hackathon, propose_challenge, review_challenge, save_resource, transition

PASSWORD = 'Demo-Hack#2026'

SKILLS = [
    ('Python', 'Backend'), ('Django', 'Backend'), ('PostgreSQL', 'Backend'), ('API REST', 'Backend'),
    ('JavaScript', 'Frontend'), ('React', 'Frontend'), ('UI/UX', 'Design'), ('Figma', 'Design'),
    ('Data Science', 'Data'), ('Machine Learning', 'Data'), ('DevOps', 'Infrastructure'),
    ('Cybersécurité', 'Sécurité'), ('Mobile', 'Frontend'),
]

# username, first name, last name, university, skills {name: level}
PEOPLE = {
    'organisatrice': ('Salma', 'Ben Youssef', 'ESPRIT', {'Python': 4}),
    'mentor.django': ('Karim', 'Trabelsi', 'ESPRIT', {'Django': 5, 'Python': 5, 'PostgreSQL': 4, 'API REST': 5}),
    'mentor.front': ('Leila', 'Mansouri', 'INSAT', {'React': 5, 'UI/UX': 4, 'JavaScript': 5}),
    'mentor.data': ('Omar', 'Gharbi', 'ENIT', {'Machine Learning': 5, 'Data Science': 5, 'Python': 4}),
    'jury.expert': ('Nadia', 'Chaabane', 'Tunisie Telecom', {'DevOps': 4, 'Cybersécurité': 5}),
    'sponsor.rep': ('Youssef', 'Hamdi', 'TechNova', {}),
    'ahmed': ('Ahmed', 'Jlassi', 'ESPRIT', {'Python': 4, 'Django': 3}),
    'mariem': ('Mariem', 'Khelifi', 'ESPRIT', {'React': 4, 'UI/UX': 4, 'Figma': 3}),
    'sami': ('Sami', 'Dridi', 'ISI', {'Data Science': 3, 'Python': 3}),
    'ines': ('Ines', 'Bouzid', 'ESPRIT', {'Mobile': 3, 'JavaScript': 3}),
}


class Command(BaseCommand):
    help = 'Create demo skills, accounts, roles, two hackathons, challenges and a sponsor. Safe to run again.'

    def add_arguments(self, parser):
        parser.add_argument('--user', help='Existing username that receives the organizer and mentor roles on both events.')
        parser.add_argument('--force', action='store_true', help='Allow the command when DEBUG is off.')

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError('Refus : DEBUG est désactivé. Cette commande est réservée au développement (--force pour passer outre).')
        own = None
        if options['user']:
            own = User.objects.filter(username=options['user']).first()
            if own is None:
                raise CommandError(f'Utilisateur introuvable : {options["user"]}')
        with transaction.atomic():
            skills = self.skills()
            users = self.people(skills)
            organizer = users['organisatrice']
            organizer.user_permissions.add(Permission.objects.get(codename='create_hackathon'))
            if own:
                own.user_permissions.add(Permission.objects.get(codename='create_hackathon'))
            ongoing = self.event(organizer, users, own, 'hackflow-demo-2026', ongoing=True)
            upcoming = self.event(organizer, users, own, 'ai-challenge-2026', ongoing=False)
        self.report(users, own, ongoing, upcoming)
        if settings.DEBUG:
            from django.core.management import call_command
            call_command('seed_m2_demo', stdout=self.stdout)

    # ---------------------------------------------------------------- data
    def skills(self):
        return {name: Skill.objects.get_or_create(name=name, defaults={'category': category})[0] for name, category in SKILLS}

    def people(self, skills):
        users = {}
        for username, (first, last, university, user_skills) in PEOPLE.items():
            user, created = User.objects.get_or_create(username=username, defaults={
                'first_name': first, 'last_name': last, 'email': f'{username.replace(".", "_")}@hackflow.test'})
            if created:
                user.set_password(PASSWORD)
                user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            if not profile.university:
                profile.university = university
                profile.biography = f'{first} participe aux hackathons HackFlow.'
                profile.save()
            for name, level in user_skills.items():
                UserSkill.objects.get_or_create(user=user, skill=skills[name], defaults={'level': level})
            users[username] = user
        return users

    def event(self, organizer, users, own, slug, ongoing):
        existing = Hackathon.objects.filter(slug=slug).first()
        if existing:
            if own:
                set_role(actor=organizer, user=own, hackathon=existing, role=Role.ORGANIZER)
                set_role(actor=organizer, user=own, hackathon=existing, role=Role.MENTOR)
            return existing
        now = timezone.now().replace(second=0, microsecond=0)
        if ongoing:
            title, start = 'HackFlow Demo 2026', now - timedelta(days=1)
            reg_open, reg_close = now - timedelta(days=14), now - timedelta(days=2)
            end = now + timedelta(days=3)
        else:
            title, start = 'AI Challenge 2026', now + timedelta(days=12)
            reg_open, reg_close = now - timedelta(days=3), now + timedelta(days=9)
            end = start + timedelta(days=3)
        deadline = end - timedelta(days=1)
        event = create_hackathon(actor=organizer, event=Hackathon(
            title=title, slug=slug, format=Hackathon.Format.HYBRID, location='ESPRIT, Ariana',
            description='Deux jours pour imaginer, construire et présenter un prototype utile, avec mentors, ateliers et jury.',
            rules='Équipes de 2 à 5 personnes. Tout code doit être produit pendant l’événement. Respect du code de conduite.',
            participation_conditions='Ouvert aux étudiants. Un seul projet par équipe.',
            start_date=start, end_date=end, registration_open=reg_open, registration_close=reg_close,
            submission_deadline=deadline, capacity=120, min_team_size=2, max_team_size=5))
        if own:
            set_role(actor=organizer, user=own, hackathon=event, role=Role.ORGANIZER)
            set_role(actor=organizer, user=own, hackathon=event, role=Role.MENTOR)
        for name in ('mentor.django', 'mentor.front', 'mentor.data'):
            set_role(actor=organizer, user=users[name], hackathon=event, role=Role.MENTOR)
        set_role(actor=organizer, user=users['jury.expert'], hackathon=event, role=Role.JURY)
        set_role(actor=organizer, user=users['sponsor.rep'], hackathon=event, role=Role.SPONSOR_REPRESENTATIVE)
        participants = ('ahmed', 'mariem', 'sami', 'ines') if ongoing else ('ahmed', 'mariem')
        for name in participants:
            set_role(actor=organizer, user=users[name], hackathon=event, role=Role.PARTICIPANT)

        tracks = {name: save_resource(actor=organizer, resource=Track(hackathon=event, name=name, description=text))
            for name, text in (('Intelligence artificielle', 'Des solutions qui apprennent et assistent.'),
                               ('Impact social', 'Technologie au service de la communauté.'))}
        phases = [('REGISTRATION', reg_open, reg_close), ('TEAM_FORMATION', reg_open + timedelta(days=1), max(reg_close, start)),
            ('DEVELOPMENT', start, deadline), ('SUBMISSION', start + timedelta(hours=6), deadline),
            ('EVALUATION', deadline, deadline + timedelta(hours=12)), ('RESULTS', deadline + timedelta(hours=12), end)]
        for kind, begin, finish in phases:
            save_resource(actor=organizer, resource=EventPhase(hackathon=event, kind=kind, start=begin, end=finish))

        for track, title_, problem in (
                (tracks['Intelligence artificielle'], 'Assistant d’orientation étudiante', 'Aider les étudiants à choisir un parcours adapté à leurs compétences.'),
                (tracks['Impact social'], 'Réduire le gaspillage alimentaire', 'Connecter commerces et associations pour redistribuer les invendus.')):
            challenge = save_resource(actor=organizer, resource=Challenge(track=track, title=title_, problem=problem,
                objectives='Concevoir un prototype fonctionnel et mesurable.', deliverables='Dépôt de code, démo vidéo et diaporama.',
                proposed_by=organizer))
            review_challenge(actor=organizer, challenge=challenge, action='approve')
            review_challenge(actor=organizer, challenge=challenge, action='publish')

        org, _ = SponsorOrganization.objects.get_or_create(name='TechNova', defaults={
            'sector': 'Logiciel', 'website': 'https://example.com', 'description': 'Éditeur de solutions cloud partenaire des hackathons.',
            'contact_name': 'Youssef Hamdi', 'contact_email': 'contact@technova.test'})
        SponsorMembership.objects.get_or_create(user=users['sponsor.rep'], organization=org)
        sponsorship = save_resource(actor=organizer, resource=Sponsorship(organization=org, hackathon=event,
            contribution_type='Prix et mentors', estimated_value=3000, status=Sponsorship.Status.CONFIRMED,
            prize_information='1er prix : 1 500 TND, 2e prix : 1 000 TND.'))
        sponsored = save_resource(actor=organizer, resource=Challenge(track=tracks['Intelligence artificielle'],
            title='Détection de fraude bancaire', problem='Repérer des transactions suspectes.', objectives='Modèle explicable.',
            deliverables='Notebook, API et rapport.', sponsorship=sponsorship, proposed_by=organizer))
        review_challenge(actor=organizer, challenge=sponsored, action='approve')
        review_challenge(actor=organizer, challenge=sponsored, action='publish')
        # A pending sponsor proposal, so the organizer can demonstrate the validation flow.
        propose_challenge(actor=users['sponsor.rep'], challenge=Challenge(track=tracks['Impact social'],
            title='Mobilité urbaine durable', problem='Fluidifier les déplacements en ville.',
            objectives='Une application utile aux usagers.', deliverables='Prototype et pitch.', sponsorship=sponsorship))

        transition(actor=organizer, event=event, target=Hackathon.Status.PUBLISHED)
        if ongoing:
            transition(actor=organizer, event=event, target=Hackathon.Status.ONGOING)
        return event

    # -------------------------------------------------------------- output
    def report(self, users, own, ongoing, upcoming):
        write = self.stdout.write
        write(self.style.SUCCESS('Données de démonstration prêtes.'))
        write('')
        write(f'Mot de passe de tous les comptes de démo : {PASSWORD}')
        write('')
        write('Compte           Rôle(s)')
        roles = {'organisatrice': 'Organisatrice (peut créer des hackathons)', 'mentor.django': 'Mentor Django/API', 'mentor.front': 'Mentor React/UI-UX',
            'mentor.data': 'Mentor Data/ML', 'jury.expert': 'Juré', 'sponsor.rep': 'Représentant sponsor TechNova',
            'ahmed': 'Participant', 'mariem': 'Participant', 'sami': 'Participant', 'ines': 'Participant'}
        for name in users:
            write(f'  {name:<15} {roles[name]}')
        if own:
            write(f'  {own.username:<15} Organisateur + mentor (vos droits ont été ajoutés)')
        write('')
        write(f'Événement en cours : /hackathons/{ongoing.slug}/')
        write(f'Événement à venir  : /hackathons/{upcoming.slug}/')
        write('Control Tower       : /hackathons/dashboard/')
