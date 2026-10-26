from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from accounts.models import User, Skill, Profile
from hackathons.test_helpers import make_event
from .tests import SetupMixin
from .models import Registration, JoinRequest, Team
from . import services, matching, evaluation


@override_settings(M2_MATCHING_ENABLED=False)
class TeamDiscoveryTests(SetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.team()
        self.a.first_name = 'PRIVATE_MEMBER_NAME'
        self.a.email = 'private@example.test'
        self.a.save()
        Profile.objects.update_or_create(user=self.a, defaults={'biography':'PRIVATE_BIO'})
        self.skill = Skill.objects.create(name='Django', category='Backend')
        services.save_need(actor=self.a, team=self.target, skill=self.skill, level=3, priority=3)

    def test_anonymous_browse_is_read_only_and_does_not_reveal_members(self):
        count = Registration.objects.count()
        response = self.client.get(reverse('teams:list',args=[self.event.slug]))
        self.assertContains(response, 'Nova')
        response = self.client.get(self.target.get_absolute_url())
        self.assertContains(response, 'Django')
        self.assertTemplateUsed(response, 'teams/preview.html')
        for private in ('PRIVATE_MEMBER_NAME','private@example.test','PRIVATE_BIO'):
            self.assertNotContains(response,private)
        self.assertEqual(Registration.objects.count(),count)
        self.assertEqual(self.client.get(reverse('teams:candidates',args=[self.event.slug,self.target.pk])).status_code,302)

    def test_resume_registration_then_explicit_application(self):
        self.client.force_login(self.b)
        apply_url = reverse('teams:apply',args=[self.event.slug,self.target.pk])
        register_url = reverse('teams:register',args=[self.event.slug])+f'?team={self.target.pk}'
        self.assertRedirects(self.client.get(apply_url),register_url)
        self.assertFalse(Registration.objects.filter(user=self.b).exists())
        self.assertEqual(self.client.post(register_url,{}).status_code,200)
        self.assertFalse(Registration.objects.filter(user=self.b).exists())
        response = self.client.post(register_url,{'accept_conditions':'on'})
        self.assertRedirects(response,apply_url)
        self.assertFalse(JoinRequest.objects.filter(registration__user=self.b).exists())
        response = self.client.post(apply_url,{'message':'Je souhaite contribuer au backend.'})
        self.assertRedirects(response,reverse('teams:inbox',args=[self.event.slug]))
        self.assertEqual(JoinRequest.objects.get(registration__user=self.b).team,self.target)
        # A duplicate application leads back to the inbox, rather than a confusing form.
        self.assertRedirects(self.client.get(apply_url),reverse('teams:inbox',args=[self.event.slug]))

    def test_return_team_is_scoped_and_closed_target_does_not_register(self):
        self.client.force_login(self.b)
        other = make_event(self.owner,slug='other')
        wrong = reverse('teams:register',args=[other.slug])+f'?team={self.target.pk}'
        self.assertEqual(self.client.get(wrong).status_code,404)
        services.update_team(actor=self.a,team=self.target,name='Nova',description='',recruiting=False)
        url = reverse('teams:register',args=[self.event.slug])+f'?team={self.target.pk}'
        self.assertRedirects(self.client.post(url,{'accept_conditions':'on'}),self.target.get_absolute_url())
        self.assertFalse(Registration.objects.filter(user=self.b).exists())

    def test_signup_preserves_team_return_and_rejects_external_redirect(self):
        target = reverse('teams:apply',args=[self.event.slug,self.target.pk])
        response = self.client.get(reverse('accounts:login')+'?next='+target)
        self.assertContains(response,'signup/?next=')
        payload = dict(username='freshparticipant',first_name='New',last_name='Participant',email='new@example.test',
            password1='Specific-test#48',password2='Specific-test#48',next=target)
        response = self.client.post(reverse('accounts:signup'),payload)
        self.assertRedirects(response,target,fetch_redirect_response=False)
        self.assertFalse(Registration.objects.filter(user__username='freshparticipant').exists())
        self.client.logout()
        payload.update(username='otherparticipant',email='other@example.test',next='https://evil.example/steal')
        self.assertRedirects(self.client.post(reverse('accounts:signup'),payload),reverse('accounts:profile'))

    def test_private_candidate_directory_authorization_and_eligibility(self):
        self.reg(self.b)
        self.client.force_login(self.b)
        self.assertEqual(self.client.get(reverse('teams:candidates',args=[self.event.slug,self.target.pk])).status_code,403)
        other_team = services.create_team(actor=self.b,event=self.event,name='Other team')
        self.reg(self.c)
        self.assertEqual([r['registration'].user for r in services.recommendations(actor=self.a,team=self.target)], [self.c])
        self.c.is_active = False
        self.c.save()
        self.assertEqual(services.recommendations(actor=self.a,team=self.target),[])


class RankingTests(SimpleTestCase):
    def test_semantic_context_can_reorder_equal_skills_but_cannot_invent_skills(self):
        team, needs, regs = evaluation.inputs(evaluation.CASES[0])
        # Deterministic vectors test ranking math, not model quality.
        with patch('teams.matching.vectors',return_value=([[1,0]]+[[0,1],[1,0],[0,1],[0,1],[0,1],[0,1],[0,1],[1,0]],'ready')):
            results = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual(results[0]['registration'].pk,'eval-b')
        novice = next(r for r in results if r['registration'].pk == 'eval-h')
        self.assertEqual(novice['matches'],[])
        self.assertFalse(novice['context_signal'])
        self.assertEqual(results[-1]['registration'].pk,'eval-h')

    def test_essential_declared_skill_dominates_secondary_skill_and_similarity(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        with patch('teams.matching.vectors',return_value=([[1,0]]+[[0,1],[0,1],[1,0],[1,0],[0,1],[0,1],[0,1],[1,0]],'ready')):
            results = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual({r['registration'].pk for r in results[:2]},{'eval-a','eval-b'})

    def test_no_needs_does_not_call_model_and_fallback_is_usable(self):
        team,needs,regs = evaluation.inputs(evaluation.CASES[0])
        with patch('teams.matching.vectors') as vector:
            results = matching.rank(team=team,needs=[],candidates=regs)
            vector.assert_not_called()
        self.assertTrue(all(r['score']==0 and r['matching_state']=='no_needs' for r in results))
        with patch('teams.matching.vectors',return_value=(None,'unavailable')):
            results = matching.rank(team=team,needs=needs,candidates=regs)
        self.assertEqual(results[0]['registration'].pk,'eval-a')
        self.assertFalse(any(r['context_signal'] for r in results))

    @override_settings(M2_MATCHING_ENABLED=True)
    def test_unprepared_model_never_loads_or_downloads_in_request(self):
        with TemporaryDirectory() as directory, override_settings(M2_MODEL_CACHE=Path(directory)):
            with patch('teams.matching._model') as model:
                self.assertEqual(matching.vectors(['test']),(None,'unavailable'))
                model.assert_not_called()

    def test_content_and_model_version_invalidate_embedding_cache(self):
        old = matching.cache_key('original biography')
        self.assertNotEqual(old,matching.cache_key('changed biography'))
        with override_settings(M2_MODEL_NAME='new-model'):
            self.assertNotEqual(old,matching.cache_key('original biography'))

    @override_settings(M2_MATCHING_ENABLED=True)
    def test_http_misses_schedule_one_bounded_job_without_loading_model(self):
        from unittest.mock import MagicMock
        cache = MagicMock()
        cache.get.return_value = None
        with TemporaryDirectory() as directory, override_settings(M2_MODEL_CACHE=Path(directory)):
            (Path(directory)/'READY').write_text('prepared')
            with patch('teams.matching.caches',{'m2_embeddings':cache}), patch('teams.matching._busy',False), \
                    patch('teams.matching._executor.submit') as submit, patch('teams.matching._model') as model:
                texts = [f'profile {i}' for i in range(200)]
                self.assertEqual(matching.vectors(texts),(None,'warming'))
                self.assertEqual(len(submit.call_args.args[1]),128)
                matching.vectors(texts)
                submit.assert_called_once()
                model.assert_not_called()

    @override_settings(M2_MATCHING_ENABLED=True)
    def test_cached_embeddings_need_no_worker_and_failed_inference_falls_back(self):
        from unittest.mock import MagicMock
        cache = MagicMock()
        cache.get.return_value = [1.0,0.0]
        with TemporaryDirectory() as directory, override_settings(M2_MODEL_CACHE=Path(directory)):
            (Path(directory)/'READY').write_text('prepared')
            with patch('teams.matching.caches',{'m2_embeddings':cache}), patch('teams.matching._executor.submit') as submit:
                self.assertEqual(matching.vectors(['hello']),([[1.0,0.0]],'ready'))
                submit.assert_not_called()
            cache.get.return_value = None
            with patch('teams.matching.caches',{'m2_embeddings':cache}), patch('teams.matching._compute',side_effect=RuntimeError):
                self.assertEqual(matching.vectors(['hello'],background=False),(None,'unavailable'))

    def test_metrics_and_blank_review_rejected(self):
        result = evaluation.metrics(['a','b','c'],{'a':2,'b':1,'c':0,'d':2})
        self.assertAlmostEqual(result['precision_at_3'],2/3)
        self.assertLess(result['ndcg_at_3'],1)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'review.csv'
            evaluation.export_sheet(path)
            with self.assertRaises(ValueError):
                evaluation.read_labels(path)
            with self.assertRaises(FileExistsError):
                evaluation.export_sheet(path)


@override_settings(DEBUG=True,M2_MATCHING_ENABLED=False)
class MatchingSeedTests(TestCase):
    def test_seed_repeats_without_resetting_password_bio_or_cancellation(self):
        call_command('seed_m2_matching_demo',stdout=StringIO())
        event = Team.objects.get(name='Passerelle').hackathon
        self.assertEqual(event.registrations.count(),28)
        self.assertEqual(event.teams.count(),6)
        captain = User.objects.get(username='m2.demo.01')
        self.assertEqual(len(services.recommendations(actor=captain,team=Team.objects.get(name='Passerelle'))),16)
        user = User.objects.get(username='m2.demo.13')
        user.set_password('My-changed-password#81')
        user.save()
        Profile.objects.filter(user=user).update(biography='My edited biography')
        services.cancel_registration(actor=user,registration=Registration.objects.get(user=user,hackathon=event))
        call_command('seed_m2_matching_demo',stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password('My-changed-password#81'))
        self.assertEqual(user.profile.biography,'My edited biography')
        self.assertEqual(Registration.objects.get(user=user,hackathon=event).status,'CANCELLED')
        self.assertEqual(event.teams.count(),6)
