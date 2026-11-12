"""Maintenance SQLite explicite, bornée et indépendante des règles comptables."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
from time import perf_counter

from django.conf import settings
from django.db import connections, DatabaseError, transaction

logger = logging.getLogger(__name__)
private_accounting_deferred = ContextVar("private_accounting_deferred", default=False)
TABLES = ("reconciliation_campaigninventory", "reconciliation_campaignsageentry",
          "reconciliation_campaignglobalcontrol", "reconciliation_campaignreview")


@contextmanager
def defer_private_accounting():
    """Diffère le seul cadrage dans un import privé ; restaure le contexte même après erreur.

    Réservé au staging SQLite : l'appelant doit préparer la copie après commit
    et avant publication. Aucun changement de décision ni effet en base ici.
    """
    token = private_accounting_deferred.set(True)
    try:
        yield
    finally:
        private_accounting_deferred.reset(token)


def statistics_missing(cursor, connection):
    """Teste les statistiques des tables utiles sans compter les grandes populations.

    Les tables vides n'exigent pas d'entrée sqlite_stat1. Les identifiants sont
    une constante interne ; les vérifications LIMIT 1 ne parcourent pas les tables.
    Retour booléen ; exceptions SQL propagées au service transactionnel.
    """
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'")
    if cursor.fetchone() is None:
        return True
    cursor.execute("SELECT DISTINCT tbl FROM sqlite_stat1 WHERE tbl IN (%s,%s,%s,%s)", TABLES)
    known = {row[0] for row in cursor.fetchall()}
    for table in set(TABLES) - known:
        cursor.execute("SELECT 1 FROM " + connection.ops.quote_name(table) + " LIMIT 1")
        if cursor.fetchone() is not None:
            return True
    return False


def maintain_statistics(*, using="default", force=False, after_import=False, automatic=True):
    """Actualise les statistiques SQLite hors transaction, ou retourne un motif de non-exécution.

    using choisit la connexion ; force permet le diagnostic explicite ; after_import
    justifie l'actualisation après chaque campagne complète committée. La politique
    automatique est désactivable sans empêcher une demande explicite. BEGIN IMMEDIATE
    sérialise les maintenances interprocessus ; les statistiques sont revérifiées
    sous verrou. Seules les métadonnées SQL changent. Une erreur est rollbackée et
    journalisée par code SQLite ou classe, sans SQL, paramètres, données métier ni traceback.
    Retourne status/reason/backend/seconds ; ne masque pas l'échec à l'appelant.
    """
    connection = connections[using]
    start = perf_counter()

    def result(status, reason):
        """Construit un bilan non sensible et journalise la décision sans paramètres métier."""
        value = {"status": status, "reason": reason, "backend": connection.vendor,
                 "seconds": perf_counter() - start}
        method = logger.error if status == "failed" else logger.info
        method("sqlite_statistics status=%s reason=%s backend=%s seconds=%.3f", status, reason,
               value["backend"], value["seconds"])
        return value

    if connection.vendor != "sqlite" or connection.settings_dict.get("ENGINE") != "django.db.backends.sqlite3":
        return result("skipped", "backend_not_sqlite")
    if automatic and not getattr(settings, "SQLITE_STATISTICS_AUTO", True) and not force:
        return result("skipped", "automatic_disabled")
    if connection.in_atomic_block:
        return result("deferred", "active_transaction")
    begun = False
    try:
        if not connection.get_autocommit() or connection.connection.in_transaction:
            return result("deferred", "active_transaction")
        with connection.cursor() as cursor:
            if not (force or after_import) and not statistics_missing(cursor, connection):
                return result("skipped", "statistics_present")
            cursor.execute("BEGIN IMMEDIATE")
            begun = True
            if not (force or after_import) and not statistics_missing(cursor, connection):
                cursor.execute("COMMIT")
                begun = False
                return result("skipped", "statistics_present_after_lock")
            cursor.execute("ANALYZE")
            cursor.execute("COMMIT")
            begun = False
        return result("executed", "forced" if force else "committed_import" if after_import else "statistics_missing")
    except DatabaseError as exc:
        if begun:
            try:
                connection.rollback()
            except DatabaseError:
                connection.close()
        return result("failed", getattr(exc.__cause__, "sqlite_errorname", None) or type(exc).__name__)


def after_campaign_commit(*, using="default"):
    """Enregistre une maintenance synchrone après commit, annulée en cas de rollback.

    Ne fait rien pour la copie privée différée, traitée explicitement avant sa
    publication. Les erreurs du service sont journalisées sans transformer un
    import committé en échec ; aucun retry ou processus d'arrière-plan implicite.
    """
    if private_accounting_deferred.get():
        return

    def completed():
        """Exécute la maintenance sur la connexion committée ; n'altère aucune campagne."""
        try:
            maintain_statistics(using=using, after_import=True)
        except Exception as exc:
            # Les données sont déjà committées : signaler sans prétendre les annuler.
            logger.error("sqlite_statistics status=failed reason=%s context=after_commit", type(exc).__name__)

    transaction.on_commit(completed, using=using)
