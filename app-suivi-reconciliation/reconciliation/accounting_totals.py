"""Sommes de consultation exactes, sans relire les inventaires ni modifier le cadrage."""

from decimal import Decimal, localcontext

from django.db import connections
from django.db.models import Aggregate, Count, TextField, Value
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import NullIf


class SQLiteDecimalSum:
    """Agrégat SQLite de scalaires textuels ; aucune accumulation en virgule flottante."""

    def __init__(self):
        """Initialise une somme absente ; distingue zéro d'un ensemble de valeurs nulles."""
        self.total = None

    def step(self, value):
        """Ajoute un montant textuel non nul en Decimal, avec 60 chiffres de précision.

        La marge couvre les montants de 28 chiffres stockés et leur cumul par
        projet. Une valeur non numérique provoque une erreur SQL explicite.
        """
        if value is not None:
            with localcontext() as context:
                context.prec = 60
                self.total = (self.total or Decimal(0)) + Decimal(value)

    def finalize(self):
        """Retourne le total textuel exact, ou NULL si aucun montant n'a été rencontré."""
        return str(self.total) if self.total is not None else None


class DecimalTextSum(Aggregate):
    """Somme SQL exacte rendue comme texte pour éviter le convertisseur float de SQLite."""

    output_field = TextField()

    def as_sqlite(self, compiler, connection, **extra_context):
        """Compile la somme SQLite enregistrée par filtered_totals, sur des scalaires texte."""
        return super().as_sql(
            compiler,
            connection,
            template="decimal_text_sum(CAST(%(expressions)s AS TEXT))",
            **extra_context,
        )

    def as_postgresql(self, compiler, connection, **extra_context):
        """Utilise NUMERIC sans échelle imposée puis retourne du texte, sans arrondi ajouté."""
        return super().as_sql(
            compiler,
            connection,
            template="CAST(SUM(CAST(%(expressions)s AS NUMERIC)) AS TEXT)",
            **extra_context,
        )


def filtered_totals(rows):
    """Retourne les quatre sommes, effectifs et absences du queryset déjà autorisé/filtré.

    Une seule requête agrégée, avant pagination ; aucun JSON projet n'est
    transféré en Python. SQLite reçoit seulement les scalaires via son agrégat
    Decimal local à la connexion ; PostgreSQL utilise SUM(NUMERIC). Une colonne
    contenant une absence rend None et son nombre de manquants, jamais une somme
    partielle présentée comme complète. Aucun effet sur les données persistées.
    """
    connection = connections[rows.db]
    if connection.vendor == "sqlite":
        connection.ensure_connection()
        connection.connection.create_aggregate("decimal_text_sum", 1, SQLiteDecimalSum)
    initial = NullIf(
        NullIf(KeyTextTransform("initial", KeyTransform("totals", "data")), Value("null")),
        Value(""),
    )
    fields = {"initial": initial, "atlas": "atlas", "sage": "sage", "gap": "gap"}
    aggregates = {"count": Count("pk")}
    for name, expression in fields.items():
        aggregates[f"sum_{name}"] = DecimalTextSum(expression)
        aggregates[f"{name}_known"] = Count(expression)
    result = rows.order_by().aggregate(**aggregates)
    for name in fields:
        result[f"{name}_missing"] = result["count"] - result.pop(f"{name}_known")
        value = result.pop(f"sum_{name}")
        result[name] = (
            Decimal(value) if value is not None and not result[f"{name}_missing"] else None
        )
    return result
