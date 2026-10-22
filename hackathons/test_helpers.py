from datetime import timedelta
from django.contrib.auth.models import Permission
from django.utils import timezone
from accounts.models import User
from .models import Hackathon, Track, Challenge, EventPhase
from .services import create_hackathon, review_challenge, save_resource


def make_owner(name='owner'):
    user = User.objects.create_user(username=name, email=f'{name}@example.test')
    user.user_permissions.add(Permission.objects.get(codename='create_hackathon'))
    return user


def make_event(owner, slug='edition', complete=False):
    now = timezone.now().replace(second=0, microsecond=0)
    event = create_hackathon(actor=owner, event=Hackathon(
        title='Hackathon ' + slug, slug=slug, description='Construire des solutions utiles', rules='Respecter le règlement',
        start_date=now+timedelta(days=2), end_date=now+timedelta(days=4),
        registration_open=now-timedelta(days=1), registration_close=now+timedelta(days=1),
        submission_deadline=now+timedelta(days=4, hours=-2), capacity=100, min_team_size=2, max_team_size=5))
    if complete:
        track = save_resource(actor=owner, resource=Track(hackathon=event, name='IA'))
        challenge = save_resource(actor=owner, resource=Challenge(track=track, title='Défi public', problem='Un problème',
            objectives='Un objectif', deliverables='Un prototype', proposed_by=owner))
        review_challenge(actor=owner, challenge=challenge, action='approve')
        review_challenge(actor=owner, challenge=challenge, action='publish')
        for kind, start, end in [
            ('REGISTRATION', event.registration_open, event.registration_close),
            ('DEVELOPMENT', event.start_date, event.submission_deadline),
            ('SUBMISSION', event.start_date+timedelta(hours=1), event.submission_deadline),
            ('EVALUATION', event.submission_deadline, event.end_date),
        ]:
            save_resource(actor=owner, resource=EventPhase(hackathon=event, kind=kind, start=start, end=end))
    return event


def event_payload(event):
    names = ['title', 'slug', 'description', 'rules', 'participation_conditions', 'location', 'format',
        'start_date', 'end_date', 'registration_open', 'registration_close', 'submission_deadline',
        'capacity', 'min_team_size', 'max_team_size']
    return {name: getattr(event, name) for name in names}
