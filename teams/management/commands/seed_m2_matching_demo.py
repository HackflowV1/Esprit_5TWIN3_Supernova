"""Isolated fictional matching playground; reruns never reset user choices."""
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import User, Profile, Skill, UserSkill
from hackathons.models import Hackathon, EventPhase, Track, Challenge
from hackathons.services import create_hackathon, save_resource, review_challenge, transition
from teams import services
from teams.models import Registration, Team, Decision

PASSWORD = 'Demo-Team#2026'
# Names, declarations and biographies are deliberately fictional. Not evaluation labels.
PEOPLE = [
    ('Adam', {'Python':4, 'Data Science':3}, 'Analyser le gaspillage et relier commerces et associations.'),
    ('Nour', {'UI/UX':4, 'Figma':4}, 'Concevoir une orientation étudiante simple et accessible.'),
    ('Yanis', {'Django':4}, 'Aider les patients à mieux comprendre leur suivi de santé.'),
    ('Lina', {'Django':3, 'PostgreSQL':3}, 'Services étudiants et accessibilité numérique.'),
    ('Amine', {'Python':3}, 'Protect personal data and secure student applications.'),
    ('Sara', {'UI/UX':3}, 'Cartographier les besoins des associations de quartier.'),
    ('Rayan', {'UI/UX':3}, 'Maquettes simples pour la solidarité alimentaire.'),
    ('Maya', {'React':3}, 'Student orientation and career guidance interfaces.'),
    ('Elyes', {'UI/UX':3}, 'Parcours patient lisible et inclusif.'),
    ('Aya', {'Python':3}, 'Backends utiles aux étudiants.'),
    ('Wassim', {'DevOps':3}, 'Automatiser les déploiements sécurisés.'),
    ('Malek', {'PostgreSQL':3}, 'Open data for local communities.'),
    ('Salma', {'Mobile':4, 'Data Science':3}, 'I build mobile apps connecting food shops with charities to reduce food waste.'),
    ('Omar', {'Mobile':4, 'Data Science':3}, 'Passionné de jeux mobiles compétitifs et de classement sportif.'),
    ('Lea', {'Mobile':2}, 'Applications mobiles pour les associations et la redistribution des repas.'),
    ('Kais', {'Django':4, 'React':3}, 'APIs for student orientation, study choices and career guidance.'),
    ('Hana', {'UI/UX':4, 'React':4}, 'Rendre les services étudiants accessibles, tester les interfaces au clavier.'),
    ('Ilyes', {'Machine Learning':4, 'Python':4}, 'Analyse de données de santé et modèles interprétables, sans diagnostic automatique.'),
    ('Rim', {'Cybersécurité':4, 'DevOps':3}, 'Audit de sécurité des applications web, protection des données personnelles.'),
    ('Bilel', {'Mobile':3, 'PostgreSQL':3}, 'Community mapping, open data and local volunteer initiatives.'),
    ('Yasmine', {'Figma':3}, 'Illustration et interfaces pour clubs culturels.'),
    ('Anas', {}, 'Je découvre le développement. Je souhaite contribuer à une équipe et apprendre.'),
    ('Dalia', {'Python':2, 'Machine Learning':2}, 'Learning interpretable models on public health datasets.'),
    ('Mehdi', {'React':4}, 'Frontends for online shopping and inventory management.'),
    ('Sonia', {'Django':3, 'UI/UX':3}, 'Des outils accessibles pour les choix d’études et les services de campus.'),
    ('Nader', {'Cybersécurité':2}, 'Apprendre à protéger les données étudiantes.'),
    ('Amina', {'Mobile':4, 'Data Science':3}, 'Logistique solidaire : développer une application de redistribution alimentaire.'),
    ('Fares', {'DevOps':4, 'PostgreSQL':4}, 'Reliable deployments and open civic data platforms.'),
]
TEAM_DATA = [
    ('Passerelle', 'Une application mobile pour redistribuer les invendus alimentaires des commerces aux associations et anticiper les besoins grâce aux données.', [('Mobile',3,3), ('Data Science',3,2)]),
    ('Boussole', 'Accompagner les étudiants dans leur orientation et leurs choix de carrière avec une interface accessible.', [('Django',3,3), ('React',3,2)]),
    ('Clair Santé', 'Un tableau de bord de suivi de santé lisible, avec une analyse de données explicable, sans diagnostic automatique.', [('Machine Learning',3,3), ('Python',3,2)]),
    ('Campus Libre', 'Des services de campus accessibles et faciles à utiliser pour tous les étudiants.', [('UI/UX',3,3), ('React',3,2)]),
    ('Sentinelle', 'Protéger les données personnelles dans les applications étudiantes et automatiser des déploiements sécurisés.', [('Cybersécurité',3,3), ('DevOps',2,2)]),
    ('Quartier', 'Une carte mobile des associations locales, de leurs actions et des besoins de bénévoles, alimentée par des données ouvertes.', [('Mobile',3,3), ('PostgreSQL',2,1)]),
]


class Command(BaseCommand):
    help = 'Create Team Lab: 28 fictional participants, six teams, diverse FR/EN skills and biographies. DEBUG only.'

    @transaction.atomic
    def handle(self, **options):
        if not settings.DEBUG:
            raise CommandError('Requires DEBUG=True; demo accounts must not be deployed in production.')
        skills = {}
        for _, declarations, _ in PEOPLE:
            for name in declarations:
                skills[name] = Skill.objects.filter(name__iexact=name).first() or Skill.objects.create(name=name, category='Démo M2')
        users = []
        for i, (name, declarations, bio) in enumerate(PEOPLE, 1):
            user, created = User.objects.get_or_create(username=f'm2.demo.{i:02d}', defaults={
                'first_name':name, 'last_name':'Démo', 'email':f'm2.demo.{i:02d}@example.test'})
            if created:
                user.set_password(PASSWORD)
                user.save()
                Profile.objects.update_or_create(user=user, defaults={'biography':bio, 'interests':bio, 'university':'Campus démo'})
                for skill, level in declarations.items():
                    UserSkill.objects.create(user=user, skill=skills[skill], level=level)
            users.append(user)
        owner, created = User.objects.get_or_create(username='m2.demo.organizer', defaults={'first_name':'Organisateur', 'last_name':'Démo'})
        if created:
            owner.set_password(PASSWORD)
            owner.save()
            owner.user_permissions.add(Permission.objects.get(codename='create_hackathon'))
        # All demo users first, then the event, matching shared service lock order.
        list(User.objects.select_for_update(no_key=True).filter(pk__in=[owner.pk, *[u.pk for u in users]]).order_by('pk'))
        event = Hackathon.objects.filter(slug='m2-team-lab').first()
        if event is None:
            now = timezone.now().replace(second=0, microsecond=0)
            event = create_hackathon(actor=owner, event=Hackathon(title='Team Lab · Trouvez vos coéquipiers', slug='m2-team-lab',
                description='Édition de démonstration : 28 profils fictifs et six idées pour tester les équipes complémentaires.',
                rules='Respect, entraide et données fictives uniquement.', participation_conditions='Démo pédagogique ouverte aux étudiants.',
                start_date=now+timedelta(days=30), end_date=now+timedelta(days=33),
                registration_open=now-timedelta(days=1), registration_close=now+timedelta(days=28),
                submission_deadline=now+timedelta(days=32), capacity=100, min_team_size=2, max_team_size=5))
            track = save_resource(actor=owner, resource=Track(hackathon=event, name='Impact étudiant'))
            challenge = save_resource(actor=owner, resource=Challenge(track=track, title='Une solution utile et accessible',
                problem='Les étudiants et associations ont besoin de services simples.', objectives='Construire une équipe complémentaire et un prototype utile.',
                deliverables='Prototype et démonstration.', proposed_by=owner))
            review_challenge(actor=owner, challenge=challenge, action='approve')
            review_challenge(actor=owner, challenge=challenge, action='publish')
            for kind, start, end in [
                ('REGISTRATION',event.registration_open,event.registration_close),
                ('TEAM_FORMATION',event.registration_open,event.start_date),
                ('DEVELOPMENT',event.start_date,event.submission_deadline),
                ('SUBMISSION',event.start_date+timedelta(days=1),event.submission_deadline),
                ('EVALUATION',event.submission_deadline,event.end_date),
            ]:
                save_resource(actor=owner, resource=EventPhase(hackathon=event, kind=kind, start=start, end=end))
            transition(actor=owner, event=event, target='PUBLISHED')
            event.refresh_from_db()
        if not services.formation_open(event):
            self.stdout.write('Existing demo calendar is closed; preserved without changes.')
            return
        regs = []
        for user in users:
            reg = Registration.objects.filter(user=user, hackathon=event).first()
            regs.append(reg if reg else services.register(actor=user, event=event, accept_conditions=True))
        for i, (name, description, needs) in enumerate(TEAM_DATA):
            if Team.objects.filter(hackathon=event, name__iexact=name).exists():
                continue
            captain, member = users[i], users[i+6]
            if regs[i].status != Registration.Status.ACCEPTED or services.active_team(captain,event):
                continue
            team = services.create_team(actor=captain,event=event,name=name,description=description)
            for skill, level, priority in needs:
                services.save_need(actor=captain,team=team,skill=skills[skill],level=level,priority=priority)
            if regs[i+6].status == Registration.Status.ACCEPTED and not services.active_team(member,event):
                invite = services.recruit(actor=captain,team=team,registration=regs[i+6],message='Invitation de démonstration.')
                services.decide(actor=member,record=invite,decision=Decision.ACCEPTED)
        self.stdout.write(self.style.SUCCESS(f'Team Lab ready: {event.registrations.count()} registrations, {event.teams.count()} teams.'))
        self.stdout.write('Captain: m2.demo.01 | Candidate: m2.demo.13 | Password for NEW accounts: '+PASSWORD)
