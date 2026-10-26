"""Add a small fictional jury walkthrough to Mentoring Lab without resetting work."""
from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from accounts.models import User, Role
from accounts.services import set_role
from hackathons.models import Hackathon, Challenge, EventPhase
from hackathons.services import phase_is_open
from projects.models import Project
from projects import services as projects
from teams.models import Team
from evaluations import services
from evaluations.models import Evaluation, EvaluationCampaign, JuryAssignment


class Command(BaseCommand):
    help = 'Seed fictional submissions, rubric and jury work in Mentoring Lab. Existing projects and evaluations are preserved.'

    @transaction.atomic
    def handle(self, **options):
        if not settings.DEBUG and not getattr(settings, 'RENDER_DEMO_MODE', False):
            raise CommandError('This command is only for the classroom demo.')
        event = Hackathon.objects.filter(slug='mentoring-lab-2026').first()
        owner = User.objects.filter(username='organisatrice', is_active=True).first()
        juror = User.objects.filter(username='jury.expert', is_active=True).first()
        if not event or not owner or not juror or event.status == 'ARCHIVED':
            self.stdout.write('Jury demo skipped: demo event/accounts unavailable or archived.')
            return
        # Acquire every demo actor before the first event lock, as in M2/M3.
        teams = list(Team.objects.filter(hackathon=event, name__in=['Nova Live', 'Horizon Live']).select_related('captain__user').order_by('pk'))
        second_juror, new_juror = User.objects.get_or_create(username='jury.demo.second', defaults={
            'first_name':'Juré', 'last_name':'Démo 2', 'email':'jury.demo.second@example.test'})
        if new_juror:
            second_juror.set_password('Demo-Hack#2026')
            second_juror.save()
        ids = [owner.pk, juror.pk, second_juror.pk, *[t.captain.user_id for t in teams]]
        list(User.objects.select_for_update(no_key=True).filter(pk__in=ids).order_by('pk'))
        challenge = Challenge.objects.filter(track__hackathon=event, track__active=True, status='PUBLISHED').first()
        if not challenge:
            self.stdout.write('Jury demo skipped: no published challenge.')
            return
        set_role(actor=owner, user=juror, hackathon=event, role=Role.JURY)
        if not event.evaluation_criteria.exists():
            services.configure_rubric(actor=owner, event=event, rows=[
                {'name':name, 'weight':Decimal(weight), 'max_score':Decimal(20), 'display_order':i}
                for i,(name,weight) in enumerate([('Utilité et innovation',40),('Réalisation technique',40),('Clarté de la présentation',20)])
            ], threshold=Decimal(25), minimum_jurors=1, validate=True)
        campaign = EvaluationCampaign.objects.filter(hackathon=event, rubric_validated=True).first()
        for i,team in enumerate(teams):
            project = Project.objects.filter(team=team).first()
            created = project is None
            if created:
                if not phase_is_open(event, EventPhase.Kind.SUBMISSION):
                    self.stdout.write('Submission window closed; no demo project created.')
                    continue
                captain = team.captain.user
                project = projects.save_project(actor=captain, team=team, data={
                    'challenge':challenge, 'title':'Campus Coach — démo jury' if i == 0 else 'Campus Partage — démo jury',
                    'problem':'Les étudiants trouvent difficilement de l’aide et des ressources sur le campus.',
                    'solution':'Un prototype accessible pour organiser l’entraide entre étudiants.',
                    'stack':'Django, PostgreSQL, JavaScript', 'pitch':'Démonstration fictive pour tester le parcours jury.', 'status':'READY'})
                version = projects.create_version(actor=captain, project=project)
                projects.save_deliverable(actor=captain, submission=version, kind='REPOSITORY',
                    url='https://example.com/fictional-campus-demo', commit='a'*40)
                projects.submit(actor=captain, submission=version, confirm_requirements=True)
                project.refresh_from_db()
            if not project.official_submission_id:
                continue  # Never submit an existing user draft on their behalf.
            assignment = JuryAssignment.objects.filter(submission=project.official_submission, juror=juror).first()
            if assignment is None:
                assignment = services.assign(actor=owner, event=event, submission=project.official_submission, juror=juror)
            if created and campaign and not Evaluation.objects.filter(assignment=assignment).exists():
                criteria = list(event.evaluation_criteria.all())
                services.save_evaluation(actor=juror, assignment=assignment,
                    scores={c.pk:(c.max_score*Decimal('0.85' if i == 0 else '0.70')).quantize(Decimal('0.01')) for c in criteria},
                    comment='Notes fictives de démonstration. À ne pas interpréter comme une évaluation réelle.', finalize=i == 0)
        # Two independent, validated fictional evaluations are required by the
        # existing divergence assistant. Never edit the first juror's locked work.
        target = Project.objects.filter(team__hackathon=event, title='Campus Coach — démo jury',
            official_submission__isnull=False).select_related('official_submission').first()
        if target and campaign:
            set_role(actor=owner, user=second_juror, hackathon=event, role=Role.JURY)
            second_assignment = JuryAssignment.objects.filter(submission=target.official_submission, juror=second_juror).first()
            if second_assignment is None:
                second_assignment = services.assign(actor=owner, event=event, submission=target.official_submission, juror=second_juror)
                services.save_evaluation(actor=second_juror, assignment=second_assignment,
                    scores={c.pk:(c.max_score*Decimal('0.35')).quantize(Decimal('0.01')) for c in event.evaluation_criteria.all()},
                    comment='Évaluation fictive volontairement différente pour tester l’analyse IA des divergences. Aucun jugement réel.',
                    finalize=True)
        self.stdout.write(self.style.SUCCESS('Mentoring Lab jury demo ready: projects, official submissions, rubric and jury assignments. Existing work preserved.'))
