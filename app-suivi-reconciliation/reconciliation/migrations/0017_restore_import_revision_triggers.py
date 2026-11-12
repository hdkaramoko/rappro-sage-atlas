"""Restaure les triggers SQLite perdus lors des reconstructions de tables Django."""

from django.db import migrations

TABLES = (
    "projects_project", "reconciliation_reconciliationtransaction", "reconciliation_reviewgroup",
    "reconciliation_linereview", "reconciliation_reviewevent", "reconciliation_campaign",
    "reconciliation_campaigninventory", "reconciliation_campaigngroup", "reconciliation_campaignreview",
    "reconciliation_multiplecontrol", "reconciliation_multipleevent", "reconciliation_controlcontribution",
    "reconciliation_campaignsageentry", "reconciliation_campaignglobalcontrol",
)


def restore_revision(apps, schema_editor):
    """Réinstalle les triggers manquants en SQLite ; aucun effet sur PostgreSQL.

    Les migrations additives de colonnes peuvent reconstruire une table SQLite
    et supprimer ses triggers. Le compteur existant est conservé. Les écritures
    suivantes incrémentent sa révision dans leur propre transaction.
    """
    if schema_editor.connection.vendor != "sqlite":
        return
    for table in TABLES:
        for event in ("INSERT", "UPDATE", "DELETE"):
            schema_editor.execute(
                f"CREATE TRIGGER IF NOT EXISTS import_revision_{table}_{event} AFTER {event} ON {table} "
                "BEGIN UPDATE reconciliation_importrevision SET revision=revision+1 WHERE id=1; END")


def remove_new_revision(apps, schema_editor):
    """Retire seulement les triggers des nouvelles photographies lors du rollback.

    Les protections préexistantes restaurées restent actives ; aucune donnée
    ni révision n'est supprimée. PostgreSQL ne nécessite aucune opération.
    """
    if schema_editor.connection.vendor != "sqlite":
        return
    for table in TABLES[-2:]:
        for event in ("INSERT", "UPDATE", "DELETE"):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS import_revision_{table}_{event}")


class Migration(migrations.Migration):
    """Préserve l'anti-concurrence après les migrations des tables d'inventaire."""

    dependencies = [("reconciliation", "0016_campaigninventory_ods_scope_and_more")]
    operations = [migrations.RunPython(restore_revision, remove_new_revision)]
