"""Préparation explicite et mesurable des projections du cadrage comptable."""

from time import perf_counter
from django.core.management.base import BaseCommand, CommandError
from reconciliation.accounting import prepare_campaign
from reconciliation.models import Campaign


class Command(BaseCommand):
    """Construit les seuls agrégats techniques, sans modifier sources ou décisions."""

    help = "Prépare le cadrage de la campagne courante, ou --campaign ID pour une photographie précise."

    def add_arguments(self, parser):
        """Ajoute l'identifiant optionnel ; aucune campagne historique n'est choisie implicitement."""
        parser.add_argument("--campaign", type=int)

    def handle(self, *args, **options):
        """Construit la projection sélectionnée et affiche durée/volume ; lève CommandError si absente."""
        campaign = Campaign.objects.filter(pk=options["campaign"]).first() if options["campaign"] else Campaign.objects.filter(is_current=True).first()
        if campaign is None:
            raise CommandError("Aucune campagne publiée correspondante")
        start = perf_counter()
        count = prepare_campaign(campaign)
        self.stdout.write(self.style.SUCCESS(f"{count} projets préparés en {perf_counter() - start:.2f} s"))
