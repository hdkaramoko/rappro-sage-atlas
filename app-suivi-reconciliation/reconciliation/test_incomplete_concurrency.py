"""Concurrence PostgreSQL des confirmations de Comptabilisé incomplets."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase

from accounts.models import User

from .business import confirm_inventory_link, correct_inventory
from .campaigns import insert_inventory
from .models import ManualAllocation
from .test_incomplete_accounting import IncompleteFixture


@skipUnless(connection.vendor == "postgresql", "Réservations concurrentes : PostgreSQL requis")
class IncompleteConcurrencyTests(IncompleteFixture, TransactionTestCase):
    """Exerce les mêmes verrous campagne et unicité de réservation que le Lot 2."""

    def test_one_of_two_incomplete_sources_can_reserve_the_same_entry(self):
        """Deux connexions simultanées ne peuvent confirmer la même écriture entière."""
        insert_inventory(self.campaign, [{**self.source, "source_id": "SECOND"}])
        identifiers = list(self.campaign.inventory.values_list("pk", flat=True))
        for pk in identifiers:
            correct_inventory(
                pk,
                self.user,
                reason="AMOUNT",
                amount="4213.38",
                comment="Justification distincte",
                expected_version=0,
            )
        barrier = Barrier(2)
        user_id, entry_id = self.user.pk, self.entry.pk

        def attempt(pk):
            """Retourne OK ou CONFLICT sur connexion isolée, puis ferme cette connexion."""
            try:
                actor = User.objects.get(pk=user_id)
                barrier.wait(timeout=20)
                try:
                    confirm_inventory_link(
                        pk,
                        actor,
                        entry_ids=[entry_id],
                        comment="Confirmation manuelle",
                        expected_version=1,
                    )
                    return "OK"
                except ValidationError:
                    return "CONFLICT"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, identifiers))
        self.assertCountEqual(results, ["OK", "CONFLICT"])
        self.assertEqual(ManualAllocation.objects.filter(active=True, entry_id=entry_id).count(), 1)
