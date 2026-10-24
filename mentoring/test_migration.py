"""Data migration 0004: the stored slot status becomes a computed availability, without losing anything."""
from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from accounts.models import Role
from accounts.services import set_role
from hackathons.test_helpers import make_owner
from .test_helpers import make_user
from .test_slots import published_event

BEFORE = [('mentoring', '0003_workshop')]
AFTER = [('mentoring', '0004_m4_plan_models')]


class SlotStatusMigrationTests(TransactionTestCase):
    def setUp(self):
        owner = make_owner()
        self.event = published_event(owner)
        self.mentor = make_user('mentor')
        set_role(actor=owner, user=self.mentor, hackathon=self.event, role=Role.MENTOR)
        # Whatever happens, leave the test database on the latest schema for the other tests.
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes()))

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_cancelled_slots_become_withdrawn_and_available_ones_stay_published(self):
        old = self.migrate(BEFORE)
        Slot = old.get_model('mentoring', 'MentorSlot')
        start = self.event.start_date + timedelta(hours=1)
        kept = Slot.objects.create(hackathon_id=self.event.pk, mentor_id=self.mentor.pk, start=start,
            end=start + timedelta(minutes=30), status='AVAILABLE')
        cancelled = Slot.objects.create(hackathon_id=self.event.pk, mentor_id=self.mentor.pk, start=start + timedelta(hours=2),
            end=start + timedelta(hours=2, minutes=30), status='CANCELLED')

        new = self.migrate(AFTER)
        Slot = new.get_model('mentoring', 'MentorSlot')
        kept, cancelled = Slot.objects.get(pk=kept.pk), Slot.objects.get(pk=cancelled.pk)
        self.assertIsNone(kept.withdrawn_at)
        self.assertIsNotNone(cancelled.withdrawn_at)
        self.assertEqual(Slot.objects.count(), 2)
        self.assertFalse(hasattr(kept, 'status'))

    def test_the_migration_can_be_reversed(self):
        new = self.migrate(AFTER)
        Slot = new.get_model('mentoring', 'MentorSlot')
        start = self.event.start_date + timedelta(hours=1)
        withdrawn = Slot.objects.create(hackathon_id=self.event.pk, mentor_id=self.mentor.pk, start=start,
            end=start + timedelta(minutes=30), withdrawn_at=start)
        free = Slot.objects.create(hackathon_id=self.event.pk, mentor_id=self.mentor.pk, start=start + timedelta(hours=2),
            end=start + timedelta(hours=2, minutes=30))

        old = self.migrate(BEFORE)
        Slot = old.get_model('mentoring', 'MentorSlot')
        self.assertEqual(Slot.objects.get(pk=withdrawn.pk).status, 'CANCELLED')
        self.assertEqual(Slot.objects.get(pk=free.pk).status, 'AVAILABLE')
