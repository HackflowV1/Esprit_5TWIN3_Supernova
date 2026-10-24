"""Fixtures shared by the M4 tests. Teams are built straight from the M2 models: the M4 tests do not
depend on the M2 registration and team-formation flow, only on its stored data."""
import itertools

from accounts.models import User
from teams.models import Registration, Team, TeamMembership
from .models import MentoringSession, SupportRequest

_counter = itertools.count(1)


def make_user(name):
    return User.objects.get_or_create(username=name, defaults={'email': f'{name}@example.test'})[0]


def make_team(event, captain, name='Nova', members=()):
    """A team of the event with an active captain and optional extra active members."""
    registration = Registration.objects.create(user=captain, hackathon=event)
    team = Team.objects.create(hackathon=event, name=name, captain=registration)
    TeamMembership.objects.create(registration=registration, team=team)
    for member in members:
        extra = Registration.objects.create(user=member, hackathon=event)
        TeamMembership.objects.create(registration=extra, team=team)
    return team


def make_request(team, author, **overrides):
    data = {'subject': 'API Django', 'description': 'Nous sommes bloqués sur le serializer.'}
    data.update(overrides)
    return SupportRequest.objects.create(hackathon=team.hackathon, team=team, author=author, **data)


def book_slot(event, slot, captain_name=None):
    """Book the slot for a fresh team (new captain unless a name is given); returns the BOOKED session."""
    captain = make_user(captain_name or f'booker{next(_counter)}')
    team = make_team(event, captain, name=f'Team {captain_name}')
    return MentoringSession.objects.create(request=make_request(team, captain), slot=slot, booked_by=captain)


def make_ongoing_event(owner, slug='live'):
    """A published, ongoing hackathon whose DEVELOPMENT phase is open *now* (slots and requests are possible)."""
    from datetime import timedelta
    from django.utils import timezone
    from hackathons.models import Challenge, EventPhase, Hackathon, Track
    from hackathons.services import create_hackathon, review_challenge, save_resource, transition
    now = timezone.now().replace(second=0, microsecond=0)
    event = create_hackathon(actor=owner, event=Hackathon(
        title='Hackathon ' + slug, slug=slug, description='Construire des solutions utiles', rules='Respecter le règlement',
        start_date=now - timedelta(hours=2), end_date=now + timedelta(days=3),
        registration_open=now - timedelta(days=3), registration_close=now - timedelta(days=1),
        submission_deadline=now + timedelta(days=2), capacity=100, min_team_size=2, max_team_size=5))
    track = save_resource(actor=owner, resource=Track(hackathon=event, name='IA'))
    challenge = save_resource(actor=owner, resource=Challenge(track=track, title='Défi', problem='Un problème',
        objectives='Un objectif', deliverables='Un prototype', proposed_by=owner))
    review_challenge(actor=owner, challenge=challenge, action='approve')
    review_challenge(actor=owner, challenge=challenge, action='publish')
    for kind, start, end in [
        ('REGISTRATION', event.registration_open, event.registration_close),
        ('DEVELOPMENT', event.start_date, event.submission_deadline),
        ('SUBMISSION', event.start_date + timedelta(hours=1), event.submission_deadline),
        ('EVALUATION', event.submission_deadline, event.end_date),
    ]:
        save_resource(actor=owner, resource=EventPhase(hackathon=event, kind=kind, start=start, end=end))
    transition(actor=owner, event=event, target='PUBLISHED')
    return transition(actor=owner, event=event, target='ONGOING')
