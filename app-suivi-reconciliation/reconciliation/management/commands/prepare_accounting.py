"""Préparation explicite et mesurable des projections du cadrage comptable."""

from time import perf_counter
from django.core.management.base import BaseCommand, CommandError
from reconciliation.accounting import prepare_campaign
from reconciliation.models import Campaign


class Command(BaseCommand):
    """Construit les seuls agrégats techniques, sans modifier sources ou décisions."""

    help = "Prépare le cadrage de la campagne courante, ou --campaign ID pour une photographie précise."

    def add_arguments(self, parser):
        """Ajoute campagne et forçage explicite des statistiques ; aucune histoire choisie implicitement."""
        parser.add_argument("--campaign", type=int)
        parser.add_argument("--force-statistics", action="store_true", help="Forcer ANALYZE sur SQLite, hors transaction.")

    def handle(self, *args, **options):
        """Maintient SQLite si nécessaire puis prépare avec progression, hors transaction globale.

        Options : campagne, force-statistics. Retour None ; écrit les seules
        projections et éventuelles statistiques. Une maintenance échouée/reportée
        arrête la préparation avant tout recalcul ; PostgreSQL est ignoré proprement.
        """
        from reconciliation.sqlite_statistics import maintain_statistics
        campaign = Campaign.objects.filter(pk=options["campaign"]).first() if options["campaign"] else Campaign.objects.filter(is_current=True).first()
        if campaign is None:
            raise CommandError("Aucune campagne publiée correspondante")
        maintenance = maintain_statistics(force=options["force_statistics"])
        self.stdout.write(f"Statistiques : {maintenance['status']} ({maintenance['reason']}), {maintenance['seconds']:.3f} s")
        self.stdout.flush()
        if maintenance["status"] in ("failed", "deferred"):
            raise CommandError("Maintenance indisponible : préparation non démarrée, consultez le journal.")
        total = campaign.inventory.filter(present=True).values_list("project_code", flat=True).union(
            campaign.sage_inventory.values_list("project_code", flat=True)).count()
        start = perf_counter()

        def progress(phase, count):
            """Affiche compteur/total et temps écoulé, sans code projet ni donnée comptable."""
            self.stdout.write(f"{count}/{total} projets · {perf_counter() - start:.1f} s")
            self.stdout.flush()

        self.stdout.write(f"Préparation : 0/{total} projets")
        self.stdout.flush()
        count = prepare_campaign(campaign, progress=progress)
        self.stdout.write(self.style.SUCCESS(f"{count} projets préparés en {perf_counter() - start:.2f} s"))
