"""Add real M2 records to the explicitly named demo event; never bypass phases."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import User, Skill
from hackathons.models import Hackathon, EventPhase
from hackathons.services import phase_is_open
from teams import services
from teams.models import Registration, Team, TeamInvitation, JoinRequest


class Command(BaseCommand):
    help = 'Create M2 demo registrations, teams, needs and pending requests. Run seed_demo first.'

    def handle(self, **options):
        if not settings.DEBUG:
            raise CommandError('Demo command requires DEBUG=True.')
        event = Hackathon.objects.filter(slug='ai-challenge-2026').first()
        if not event:
            raise CommandError('Run seed_demo first.')
        if not phase_is_open(event, EventPhase.Kind.REGISTRATION) or not services.formation_open(event):
            self.stdout.write('M2 demo skipped: the demo registration / team formation periods are closed.')
            return
        with transaction.atomic():
            users = {name: User.objects.get(username=name) for name in ('ahmed', 'mariem', 'sami', 'ines')}
            # The command composes several service calls in one transaction:
            # acquire every demo user first, before the first event lock.
            list(User.objects.select_for_update(no_key=True).filter(pk__in=[user.pk for user in users.values()]).order_by('pk'))
            regs = {}
            for name, user in users.items():
                # Seeding must not undo a cancellation made while trying the demo.
                regs[name] = Registration.objects.filter(user=user, hackathon=event).first()
                if regs[name] is None:
                    regs[name] = services.register(actor=user, event=event, accept_conditions=True)
            nova = Team.objects.filter(hackathon=event, name__iexact='Nova').first()
            if nova is None and regs['ahmed'].status == Registration.Status.ACCEPTED and not services.active_team(users['ahmed'], event):
                nova = services.create_team(actor=users['ahmed'], event=event, name='Nova', description='Un assistant d’orientation pour aider les étudiants à trouver leur voie. Notre backend prend forme ; nous cherchons un regard UI/UX pour rendre le parcours simple et agréable.')
                services.save_need(actor=users['ahmed'], team=nova, skill=Skill.objects.get(name='UI/UX'), level=3, priority=3)
                services.save_need(actor=users['ahmed'], team=nova, skill=Skill.objects.get(name='React'), level=2, priority=2)
            horizon = Team.objects.filter(hackathon=event, name__iexact='Horizon').first()
            if horizon is None and regs['sami'].status == Registration.Status.ACCEPTED and not services.active_team(users['sami'], event):
                horizon = services.create_team(actor=users['sami'], event=event, name='Horizon', description='Moins de gaspillage, plus de solidarité. Une application mobile pour relier les commerces et les associations, avec une approche data pour anticiper les besoins.')
                services.save_need(actor=users['sami'], team=horizon, skill=Skill.objects.get(name='Mobile'), level=2, priority=3)
            if nova and regs['mariem'].status == Registration.Status.ACCEPTED and nova.closed_at is None and nova.recruiting and nova.places_left and not services.active_team(users['mariem'], event) and not JoinRequest.objects.filter(team=nova, registration=regs['mariem']).exists():
                services.recruit(actor=users['mariem'], team=nova, message='Je peux travailler sur les maquettes Figma et le frontend React. Votre idée d’orientation me parle !')
            if horizon and regs['ines'].status == Registration.Status.ACCEPTED and horizon.captain.user_id == users['sami'].pk and horizon.closed_at is None and horizon.recruiting and horizon.places_left and not services.active_team(users['ines'], event) and not TeamInvitation.objects.filter(team=horizon, registration=regs['ines']).exists():
                services.recruit(actor=users['sami'], team=horizon, registration=regs['ines'], message='Ton expérience mobile serait parfaite pour notre projet. On en discute ?')
        self.stdout.write(self.style.SUCCESS('M2 demo ready: Nova, Horizon, four registrations, skill needs, an application and an invitation.'))
