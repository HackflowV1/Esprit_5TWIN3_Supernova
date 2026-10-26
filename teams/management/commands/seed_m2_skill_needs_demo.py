"""An ordinary, published hackathon for Sami to try the needs assistant end to end."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User, Skill
from hackathons.models import Hackathon, Track, Challenge, EventPhase
from hackathons.services import create_hackathon, save_resource, review_challenge, transition
from teams import services
from teams.models import Registration


IDEA = (
    'We need to simplify the donation signup steps, test screen usability with volunteers, '
    'and make every action accessible using only the keyboard. We will sketch the screens in Figma.'
)


class Command(BaseCommand):
    help = 'Create Campus solidaire / Passerelle for Sami, with an English idea and no prefilled skill needs. Preserves edits on rerun.'

    @transaction.atomic
    def handle(self, **options):
        if not settings.DEBUG:
            raise CommandError('This fictional demonstration requires DEBUG=True.')
        sami = User.objects.filter(username='sami', is_active=True).first()
        owner = User.objects.filter(username='organisatrice', is_active=True).first()
        if not sami or not owner:
            raise CommandError('Run seed_demo first to create Sami and the demonstration organizer.')
        if not Skill.objects.filter(name='Figma').exists() or not Skill.objects.filter(name='UI/UX').exists():
            raise CommandError('Run seed_demo first to populate the existing skill catalogue.')
        list(User.objects.select_for_update(no_key=True).filter(pk__in=[sami.pk, owner.pk]).order_by('pk'))
        event = Hackathon.objects.filter(slug='campus-solidaire-2026').first()
        if event is None:
            now = timezone.now().replace(second=0, microsecond=0)
            event = create_hackathon(actor=owner, event=Hackathon(
                title='Campus solidaire 2026', slug='campus-solidaire-2026',
                description='Des services simples et accessibles pour les associations étudiantes. Édition de démonstration avec des données fictives.',
                rules='Respect, entraide et données fictives uniquement.',
                participation_conditions='Ouvert aux étudiants souhaitant construire un prototype solidaire.',
                format=Hackathon.Format.HYBRID, location='ESPRIT',
                start_date=now + timedelta(days=30), end_date=now + timedelta(days=33),
                registration_open=now - timedelta(days=1), registration_close=now + timedelta(days=28),
                submission_deadline=now + timedelta(days=32), capacity=100, min_team_size=1, max_team_size=5))
            track = save_resource(actor=owner, resource=Track(hackathon=event, name='Solidarité et accessibilité'))
            challenge = save_resource(actor=owner, resource=Challenge(
                track=track, title='Faciliter les collectes solidaires',
                problem='Les bénévoles abandonnent des parcours d’inscription trop complexes.',
                objectives='Concevoir un parcours de don simple, testé et accessible.',
                deliverables='Un prototype et une démonstration du parcours.', proposed_by=owner))
            review_challenge(actor=owner, challenge=challenge, action='approve')
            review_challenge(actor=owner, challenge=challenge, action='publish')
            for kind, start, end in (
                ('REGISTRATION', event.registration_open, event.registration_close),
                ('TEAM_FORMATION', event.registration_open, event.start_date),
                ('DEVELOPMENT', event.start_date, event.submission_deadline),
                ('SUBMISSION', event.start_date + timedelta(days=1), event.submission_deadline),
                ('EVALUATION', event.submission_deadline, event.end_date),
            ):
                save_resource(actor=owner, resource=EventPhase(hackathon=event, kind=kind, start=start, end=end))
            transition(actor=owner, event=event, target=Hackathon.Status.PUBLISHED)
            event.refresh_from_db()
        registration = Registration.objects.filter(user=sami, hackathon=event).first()
        if registration is None:
            services.register(actor=sami, event=event, accept_conditions=True)
        elif registration.status != Registration.Status.ACCEPTED:
            raise CommandError('Sami cancelled this registration; preserved without changes.')
        team = services.active_team(sami, event)
        if team is None:
            team = services.create_team(actor=sami, event=event, name='Passerelle', description=IDEA)
        elif not services.is_captain(sami, team):
            raise CommandError('Sami is no longer captain here; memberships were preserved.')
        self.stdout.write(self.style.SUCCESS(f'{event.title} / {team.name} ready for Sami.'))
        self.stdout.write(f'Open: /participation/{event.slug}/teams/{team.pk}/needs/add/?mode=idea')
        self.stdout.write('Analyze the prefilled idea: Figma is explicit; UI/UX is inferred by the current ML model.')
        self.stdout.write('No needs were added. Existing ideas, needs, passwords and Horizon remain unchanged.')
