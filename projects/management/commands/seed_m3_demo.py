"""Create an isolated M3 walkthrough through the public M1/M2/M3 services."""
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from hackathons.models import Hackathon, Track, Challenge, EventPhase
from hackathons import services as events
from teams import services as teams
from projects import services

SLUG = 'm3-project-lab'
PASSWORD = 'Demo-M3#2026'
USERNAMES = ['m3.organizer', 'm3.captain', 'm3.builder', 'm3.captain2', 'm3.designer']


class Command(BaseCommand):
    help = 'Create a separate M3 demo event, two projects and local demo accounts; never reset existing data.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Cette commande est réservée au développement (DEBUG=True).')
        if Hackathon.objects.filter(slug=SLUG).exists():
            self.stdout.write('La démo M3 existe déjà ; aucune donnée modifiée.')
            return
        if User.objects.filter(username__in=USERNAMES).exists():
            raise CommandError('Un identifiant de démo M3 existe déjà. Aucune donnée modifiée.')
        users = [User.objects.create_user(username=name, password=PASSWORD) for name in USERNAMES]
        owner, captain, builder, captain2, designer = users
        owner.user_permissions.add(Permission.objects.get(codename='create_hackathon'))
        now = timezone.now().replace(second=0, microsecond=0)
        deadline = now + timedelta(days=6)
        event = events.create_hackathon(actor=owner, event=Hackathon(title='M3 · Project Lab', slug=SLUG,
            description='Une édition de démonstration dédiée aux projets, étapes et versions.',
            rules='Données fictives. Respecter les autres équipes.',
            start_date=now-timedelta(days=1), end_date=now+timedelta(days=7),
            registration_open=now-timedelta(days=2), registration_close=now+timedelta(days=1),
            submission_deadline=deadline, capacity=20, min_team_size=2, max_team_size=5))
        track = events.save_resource(actor=owner, resource=Track(hackathon=event, name='Campus durable'))
        challenge = events.save_resource(actor=owner, resource=Challenge(track=track, title='Un campus plus solidaire',
            problem='Faciliter l’entraide entre étudiants.', objectives='Proposer une solution accessible.',
            deliverables='Un dépôt de code avec commit et un pitch décrivant le prototype.', proposed_by=owner))
        events.review_challenge(actor=owner, challenge=challenge, action='approve')
        events.review_challenge(actor=owner, challenge=challenge, action='publish')
        for kind, start, end in [
            ('REGISTRATION', event.registration_open, event.registration_close),
            ('TEAM_FORMATION', event.registration_open, now+timedelta(days=2)),
            ('DEVELOPMENT', event.start_date, deadline),
            ('SUBMISSION', now-timedelta(hours=1), deadline),
            ('EVALUATION', deadline, event.end_date),
        ]:
            events.save_resource(actor=owner, resource=EventPhase(hackathon=event, kind=kind, start=start, end=end))
        events.transition(actor=owner, event=event, target='PUBLISHED')
        event.refresh_from_db()
        for leader, member, name, title in [
            (captain, builder, 'Nova M3', 'Campus Care'),
            (captain2, designer, 'Horizon M3', 'Campus Share'),
        ]:
            teams.register(actor=leader, event=event, accept_conditions=True)
            registration = teams.register(actor=member, event=event, accept_conditions=True)
            team = teams.create_team(actor=leader, event=event, name=name, description='Équipe de démonstration M3.')
            invitation = teams.recruit(actor=leader, team=team, registration=registration)
            teams.decide(actor=member, record=invitation, decision='ACCEPTED')
            project = services.save_project(actor=leader, team=team, data={
                'challenge': challenge, 'title': title, 'problem': 'Les étudiants trouvent difficilement de l’aide sur le campus.',
                'solution': 'Une plateforme d’entraide pour partager compétences et ressources.',
                'stack': 'Python, Django, PostgreSQL', 'pitch': 'Un campus où chaque étudiant peut aider et être aidé.', 'status': 'BUILDING'})
            for label, state, progress in [('Prototype', 'DONE', 100), ('MVP', 'DOING', 20)]:
                services.save_milestone(actor=leader, project=project, data={'title': label,
                    'due_at': now+timedelta(days=3), 'state': state, 'progress': progress})
            count = 3 if leader == captain else 1
            for _ in range(count):
                submission = services.create_version(actor=leader, project=project)
                services.save_deliverable(actor=leader, submission=submission, kind='REPOSITORY',
                    url='https://example.com/demo-repository', commit='a'*40)
            if leader == captain:
                services.submit(actor=leader, submission=submission, confirm_requirements=True)
                services.publication(actor=leader, project=project, action='request')
                services.publication(actor=owner, project=project, action='publish')
        self.stdout.write(self.style.SUCCESS('Démo M3 créée : Campus Care (v3 officielle) et Campus Share (brouillon), progression 60 %.'))
        self.stdout.write('Comptes de démo : ' + ', '.join(USERNAMES))
        self.stdout.write('Mot de passe de démonstration : ' + PASSWORD)
        self.stdout.write('Les URL et commits de démonstration sont fictifs. Remplacez-les pour un dépôt réel.')
