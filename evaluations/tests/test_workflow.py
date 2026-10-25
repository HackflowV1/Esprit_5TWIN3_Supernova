from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, Role, RoleAssignment
from accounts.services import set_role
from hackathons.test_helpers import make_owner, make_event
from teams.models import Registration, Team, TeamMembership
from projects.models import Project, Submission, Deliverable
from projects.services import project_snapshot
from evaluations.models import (EvaluationCriterion, Evaluation, CriterionScore, JuryAssignment, ReviewHistory, ResultPublication, Prize, Award)
from evaluations import services


class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_owner()
        cls.event = make_event(cls.owner, complete=True)
        cls.participant = User.objects.create_user('participant')
        cls.juror = User.objects.create_user('juror')
        cls.other = User.objects.create_user('other')
        cls.stranger = User.objects.create_user('stranger')
        for user in [cls.juror, cls.other]:
            set_role(actor=cls.owner, user=user, hackathon=cls.event, role=Role.JURY)
        set_role(actor=cls.owner, user=cls.participant, hackathon=cls.event, role=Role.PARTICIPANT)
        reg = Registration.objects.create(user=cls.participant, hackathon=cls.event)
        cls.team = Team.objects.create(hackathon=cls.event, name='Nova', captain=reg)
        TeamMembership.objects.create(registration=reg, team=cls.team)
        cls.project = Project.objects.create(team=cls.team, challenge=cls.event.tracks.get().challenges.get(), title='Campus Care', problem='Problem', solution='Solution', stack='Django')
        cls.sub = Submission.objects.create(project=cls.project, version=1, status='OFFICIAL', created_by=cls.participant, snapshot=project_snapshot(cls.project))
        cls.project.official_submission = cls.sub
        cls.project.save()

    def configure(self, minimum=1):
        services.configure_rubric(actor=self.owner, event=self.event, rows=[{'name': 'Innovation', 'weight': Decimal(30), 'max_score': Decimal(20), 'display_order': 0}, {'name': 'Technique', 'weight': Decimal(70), 'max_score': Decimal(10), 'display_order': 1}], threshold=Decimal(25), minimum_jurors=minimum, validate=True)
        return list(self.event.evaluation_criteria.all())

    def assign(self, juror=None):
        return services.assign(actor=self.owner, event=self.event, submission=self.sub, juror=juror or self.juror)

    def evaluate(self, assignment=None, low=False, finalize=True):
        assignment = assignment or self.assign()
        criteria = list(self.event.evaluation_criteria.all())
        return services.save_evaluation(actor=assignment.juror, assignment=assignment, scores={criteria[0].pk: Decimal(2 if low else 18), criteria[1].pk: Decimal(1 if low else 8)}, comment='PRIVATE_COMMENT_123', finalize=finalize)

    def after_deadline(self):
        return patch('evaluations.services.timezone.now', return_value=self.event.submission_deadline + timedelta(minutes=1))

    def test_full_workflow_publication_award_and_confidentiality(self):
        self.configure()
        evaluation = self.evaluate()
        self.assertEqual(evaluation.total, Decimal('83.0000'))
        with self.after_deadline():
            publication = services.validate_ranking(actor=self.owner, event=self.event)
            self.assertIsNone(publication.published_at)
            self.assertNotContains(self.client.get(reverse('evaluations:results', args=[self.event.slug])), 'Campus Care')
            services.publish(actor=self.owner, publication=publication)
        prize = services.save_prize(actor=self.owner, event=self.event, data={'name': 'Grand prix', 'description': 'Prototype', 'sponsorship': None})
        award = services.award(actor=self.owner, prize=prize, submission=self.sub)
        self.assertEqual(services.award(actor=self.owner, prize=prize, submission=self.sub).pk, award.pk)
        response = self.client.get(reverse('evaluations:results', args=[self.event.slug]))
        self.assertContains(response, 'Campus Care')
        self.assertContains(response, 'Grand prix')
        self.assertNotContains(response, 'PRIVATE_COMMENT_123')
        self.assertNotContains(response, 'review_key')
        self.assertNotContains(response, 'juror')
        publication.refresh_from_db()
        publication.ranking = []
        with self.assertRaises(ValidationError):
            publication.save()

    def test_assignment_requires_real_official_current_submission_and_role(self):
        with self.assertRaises(ValidationError):
            services.assign(actor=self.owner, event=self.event, submission=self.sub, juror=self.participant)
        draft = Submission.objects.create(project=self.project, version=2, created_by=self.participant)
        with self.assertRaises(ValidationError):
            services.assign(actor=self.owner, event=self.event, submission=draft, juror=self.juror)
        self.assertEqual(self.assign().pk, self.assign().pk)
        with self.assertRaises(PermissionDenied):
            services.assign(actor=self.juror, event=self.event, submission=self.sub, juror=self.other)

    def test_rubric_invalid_rolls_back_and_freezes_after_draft(self):
        with self.assertRaises(ValidationError):
            services.configure_rubric(actor=self.owner, event=self.event, rows=[{'name': 'Bad', 'weight': Decimal(90), 'max_score': Decimal(10), 'display_order': 0}], threshold=25, minimum_jurors=1, validate=True)
        self.assertEqual(EvaluationCriterion.objects.count(), 0)
        self.configure()
        self.evaluate(finalize=False)
        c = self.event.evaluation_criteria.first()
        c.weight = Decimal(40)
        with self.assertRaises(ValidationError):
            c.save()
        with self.assertRaises(ValidationError):
            c.delete()
        with self.assertRaises(ValidationError):
            self.configure()

    def test_draft_partial_final_complete_and_locked(self):
        criteria = self.configure()
        assignment = self.assign()
        ev = services.save_evaluation(actor=self.juror, assignment=assignment, scores={criteria[0].pk: Decimal(15)}, finalize=False)
        self.assertIsNone(ev.total)
        with self.assertRaises(ValidationError):
            services.save_evaluation(actor=self.juror, assignment=assignment, scores={}, finalize=True)
        ev = self.evaluate(assignment)
        with self.assertRaises(ValidationError):
            self.evaluate(assignment)
        ev.comment = 'changed'
        with self.assertRaises(ValidationError):
            ev.save()
        score = ev.scores.first()
        score.score = 1
        with self.assertRaises(ValidationError):
            score.save()
        with self.assertRaises(ValidationError):
            score.delete()
        with self.assertRaises(ValidationError):
            services.change_assignment(actor=self.owner, assignment=assignment, action='remove')
        self.client.force_login(self.juror)
        self.assertEqual(self.client.post(reverse('evaluations:evaluate', args=[assignment.pk]), {'action': 'finalize'}).status_code, 403)

    def test_unassigned_and_participant_cannot_evaluate_or_inspect_private_notes(self):
        self.configure()
        assignment = self.assign()
        ev = self.evaluate(assignment)
        for user in [self.other, self.participant, self.stranger]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse('evaluations:evaluate', args=[assignment.pk])).status_code, 403)
                self.assertEqual(self.client.get(reverse('evaluations:review', args=[self.event.slug, ev.pk])).status_code, 403)
                self.assertEqual(self.client.get(reverse('evaluations:ranking', args=[self.event.slug])).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('evaluations:review', args=[self.event.slug, ev.pk])), 'PRIVATE_COMMENT_123')

    def test_conflict_blocks_until_human_resolution(self):
        self.configure()
        assignment = self.assign()
        services.change_assignment(actor=self.juror, assignment=assignment, action='report', reason='Collaboration antérieure')
        with self.assertRaises(ValidationError):
            self.evaluate(assignment)
        with self.assertRaises(PermissionDenied):
            services.change_assignment(actor=self.other, assignment=assignment, action='resolve', reason='OK')
        services.change_assignment(actor=self.owner, assignment=assignment, action='resolve', reason='Vérifié : sans incidence')
        self.evaluate(assignment)
        self.assertEqual(ReviewHistory.objects.count(), 2)

    def test_divergence_blocks_publication_and_resolution_is_invalidated(self):
        self.configure(minimum=2)
        self.evaluate()
        second = self.assign(self.other)
        self.evaluate(second, low=True)
        row = services.ranking(self.event)[0]
        self.assertTrue(row['divergent'])
        self.assertEqual(row['spread'], '73.0000')
        with self.after_deadline():
            with self.assertRaises(ValidationError):
                services.validate_ranking(actor=self.owner, event=self.event)
            services.resolve_divergence(actor=self.owner, event=self.event, submission=self.sub, reason='Écart vérifié avec le jury')
            self.assertTrue(services.ranking(self.event)[0]['resolved'])
            services.validate_ranking(actor=self.owner, event=self.event)
        third = User.objects.create_user('third')
        set_role(actor=self.owner, user=third, hackathon=self.event, role=Role.JURY)
        self.evaluate(self.assign(third))
        self.assertFalse(services.ranking(self.event)[0]['resolved'])

    def test_publication_checks_deadline_missing_reviews_and_minimum(self):
        self.configure(minimum=2)
        self.evaluate()
        with self.after_deadline(), self.assertRaises(ValidationError):
            services.validate_ranking(actor=self.owner, event=self.event)
        self.assign(self.other)
        with self.after_deadline(), self.assertRaises(ValidationError):
            services.validate_ranking(actor=self.owner, event=self.event)
        self.evaluate(self.assign(self.other))
        with self.assertRaises(ValidationError):
            services.validate_ranking(actor=self.owner, event=self.event)
        with self.after_deadline():
            p = services.validate_ranking(actor=self.owner, event=self.event)
            with self.assertRaises(PermissionDenied):
                services.publish(actor=self.participant, publication=p)
            self.assertEqual(services.validate_ranking(actor=self.owner, event=self.event).pk, p.pk)
            RoleAssignment.objects.filter(user=self.other, role=Role.JURY).update(status='REVOKED')
            with self.assertRaises(ValidationError):
                services.publish(actor=self.owner, publication=p)

    def test_hackathons_are_isolated(self):
        self.configure()
        outsider = make_owner('outside_owner')
        event = make_event(outsider, slug='outside', complete=True)
        with self.assertRaises(ValidationError):
            services.assign(actor=outsider, event=event, submission=self.sub, juror=self.juror)
        self.client.force_login(outsider)
        for name in ['dashboard', 'rubric', 'assignments', 'anomalies', 'ranking', 'prizes']:
            self.assertEqual(self.client.get(reverse('evaluations:'+name, args=[self.event.slug])).status_code, 403)

    def test_reopened_m3_submission_blocks_publication_and_old_assignment_access(self):
        self.configure()
        assignment = self.assign()
        self.evaluate(assignment)
        Project.objects.filter(pk=self.project.pk).update(official_submission=None)
        with self.after_deadline(), self.assertRaises(ValidationError):
            services.validate_ranking(actor=self.owner, event=self.event)
        with self.assertRaises(ValidationError):
            services.require_assignment(self.juror, JuryAssignment.objects.get(pk=assignment.pk))

    def test_organizer_pages_render_and_csrf_sensitive_actions(self):
        self.configure()
        self.evaluate()
        self.client.force_login(self.owner)
        for name in ['hub', 'dashboard', 'rubric', 'assignments', 'anomalies', 'ranking', 'prizes']:
            url = reverse('evaluations:'+name, args=[] if name == 'hub' else [self.event.slug])
            self.assertEqual(self.client.get(url).status_code, 200, name)
        self.client.force_login(self.juror)
        self.assertEqual(self.client.get(reverse('evaluations:hub')).status_code, 200)
        self.assertEqual(self.client.get(reverse('evaluations:evaluate', args=[self.assign().pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('evaluations:assignment-action', args=[self.assign().pk])).status_code, 405)

    def test_prize_requires_same_event_confirmed_sponsor_and_published_winner(self):
        self.configure()
        prize = services.save_prize(actor=self.owner, event=self.event, data={'name': 'Prix', 'description': '', 'sponsorship': None})
        with self.assertRaises(ValidationError):
            services.award(actor=self.owner, prize=prize, submission=self.sub)
        self.evaluate()
        with self.after_deadline():
            p = services.validate_ranking(actor=self.owner, event=self.event)
            services.publish(actor=self.owner, publication=p)
        services.award(actor=self.owner, prize=prize, submission=self.sub)
        draft = Submission.objects.create(project=self.project, version=2, created_by=self.participant)
        with self.assertRaises(ValidationError):
            services.award(actor=self.owner, prize=prize, submission=draft)
        with self.assertRaises(ValidationError):
            services.save_prize(actor=self.owner, event=self.event, prize=prize, data={'name': 'Changed', 'description': '', 'sponsorship': None})
    def test_ties_share_competition_rank_and_snapshot_is_used(self):
        self.configure()
        self.evaluate()
        reg = Registration.objects.create(user=self.stranger, hackathon=self.event)
        team = Team.objects.create(hackathon=self.event, name='Second', captain=reg)
        project = Project.objects.create(team=team, challenge=self.project.challenge, title='Second project', problem='P', solution='S', stack='Python')
        sub = Submission.objects.create(project=project, version=1, status='OFFICIAL', created_by=self.stranger, snapshot=project_snapshot(project))
        project.official_submission = sub
        project.save()
        a = services.assign(actor=self.owner, event=self.event, submission=sub, juror=self.juror)
        self.evaluate(a)
        rows = services.ranking(self.event)
        self.assertEqual([r['rank'] for r in rows], [1, 1])
        Project.objects.filter(pk=self.project.pk).update(title='Changed live title')
        self.assertEqual(services.ranking(self.event)[0]['project'], 'Campus Care')

    def test_stale_validation_refuses_publication(self):
        self.configure()
        self.evaluate()
        with self.after_deadline():
            p = services.validate_ranking(actor=self.owner, event=self.event)
            self.evaluate(self.assign(self.other))
            with self.assertRaises(ValidationError):
                services.publish(actor=self.owner, publication=p)
            p2 = services.validate_ranking(actor=self.owner, event=self.event)
            self.assertEqual(p2.version, 2)
            services.publish(actor=self.owner, publication=p2)
        self.assertEqual(ResultPublication.objects.count(), 2)
        self.assertIsNone(ResultPublication.objects.get(pk=p.pk).published_at)

    def test_team_member_conflict_cannot_be_overridden(self):
        self.configure()
        # Simulate an inconsistent external role import: M5 still checks M2 membership.
        RoleAssignment.objects.filter(user=self.participant, role=Role.PARTICIPANT).update(status='REVOKED')
        set_role(actor=self.owner, user=self.participant, hackathon=self.event, role=Role.JURY)
        with self.assertRaises(ValidationError):
            services.assign(actor=self.owner, event=self.event, submission=self.sub, juror=self.participant)

    def test_foreign_criterion_and_score_bounds(self):
        criteria = self.configure()
        assignment = self.assign()
        with self.assertRaises(ValidationError):
            services.save_evaluation(actor=self.juror, assignment=assignment, scores={999999: 3})
        with self.assertRaises(ValidationError):
            services.save_evaluation(actor=self.juror, assignment=assignment, scores={criteria[0].pk: Decimal('-1')})
        with self.assertRaises(ValidationError):
            services.save_evaluation(actor=self.juror, assignment=assignment, scores={criteria[0].pk: Decimal('21')})
        self.assertFalse(Evaluation.objects.exists())

    def test_sponsor_reuses_confirmed_m1_partnership(self):
        from hackathons.models import SponsorOrganization, Sponsorship
        organization = SponsorOrganization.objects.create(name='University')
        partnership = Sponsorship.objects.create(hackathon=self.event, organization=organization, contribution_type='Prix', status='PROPOSED')
        data = {'name': 'Sponsor prize', 'description': '', 'sponsorship': partnership}
        with self.assertRaises(ValidationError):
            services.save_prize(actor=self.owner, event=self.event, data=data)
        partnership.status = 'CONFIRMED'
        partnership.save()
        prize = services.save_prize(actor=self.owner, event=self.event, data=data)
        self.assertEqual(prize.sponsorship.organization_id, organization.pk)

    def test_revoked_juror_and_archived_hackathon(self):
        self.configure()
        assignment = self.assign()
        RoleAssignment.objects.filter(user=self.juror, role=Role.JURY).update(status='REVOKED')
        with self.assertRaises(PermissionDenied):
            self.evaluate(assignment)
        from hackathons.models import Hackathon
        Hackathon.objects.filter(pk=self.event.pk).update(status='ARCHIVED')
        with self.assertRaises(PermissionDenied):
            self.assign()
