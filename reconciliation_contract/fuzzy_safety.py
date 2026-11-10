"""Preuve bilatérale des AUTO fuzzy, indépendante du score et du classement."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from decimal import Decimal

from . import money, text

FUZZY_RULES = frozenset({"MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW"})
INDIVIDUAL_RULES = FUZZY_RULES | {"MATCH_EXACT"}


class FuzzySafety:
    """Indexe les sources complètes pour prouver une unicité dans les deux sens.

    Les itérables canoniques Atlas/Sage sont consommés une seule fois. Les
    doublons sont conservés : ils interdisent une preuve individuelle certaine.
    La recherche par projet/tiers/exercice/BAP puis montant évite un produit croisé.
    Aucun effet de bord externe, aucune conversion de devise ni comparaison fuzzy.
    """

    def __init__(self, atlas, sage):
        """Construit deux index triés ; paramètres canoniques, retour implicite None.

        Seuls Comptabilisé et Envoyé SAGE peuvent concurrencer une réservation.
        Les sources incomplètes ne deviennent jamais des candidats autorisés.
        """
        self.atlas = self._index(atlas, sage=False)
        self.sage = self._index(sage, sage=True)

    @staticmethod
    def _index(rows, *, sage):
        """Retourne les blocs triés de sources sans dédupliquer les occurrences.

        `sage` choisit le montant canonique ; les valeurs manquantes sont ignorées.
        Le résultat reste privé en mémoire, sans lecture ni écriture externe.
        """
        blocks = defaultdict(list)
        for row in rows:
            if not sage and row.get("bap_status") not in ("Envoyé SAGE", "Comptabilisé"):
                continue
            amount = money(row.get("amount") if sage else row.get(
                "total_sage_charges" if row.get("bap_status") == "Comptabilisé" else "total_project_charges"))
            key = (text(row.get("project_code")).upper(),
                   text(row.get("third_party") if sage else row.get("sage_third_party_code")).upper(),
                   row.get("fiscal_year"), text(row.get("matching_reference") if sage else row.get("sage_bap_number")).upper())
            if amount is not None and all(v not in (None, "") for v in key[:3]):
                blocks[key].append((amount, row))
        result = {}
        for key, values in blocks.items():
            values.sort(key=lambda value: value[0])
            result[key] = ([value[0] for value in values], [value[1] for value in values])
        return result

    @staticmethod
    def _near(index, key, amount):
        """Retourne les occurrences compatibles au centime et de même signe.

        Paramètres : index privé, clé structurée et Decimal fini. Sans effet
        de bord ; aucune exception métier n'est masquée.
        """
        amounts, rows = index.get(key, ([], []))
        start = bisect_left(amounts, amount - Decimal("0.01"))
        end = bisect_right(amounts, amount + Decimal("0.01"))
        matches = []
        for position in range(start, end):
            if amounts[position] * amount >= 0:
                matches.append(rows[position])
                if len(matches) == 2:
                    break
        return matches

    def verify(self, atlas, entry):
        """Vérifie une paire canonique ; retourne None ou lève ValueError motivée.

        Exige projet/tiers/exercice identiques, montant signé au centime,
        référence Sage complète, même BAP et unicité bilatérale sur ce périmètre.
        Les devises d'origine n'interviennent pas : les charges sont déjà en EUR.
        Un concurrent sans BAP reste potentiellement concurrent et bloque l'AUTO.
        Ni le score ni le libellé ne départagent les concurrents. Lecture pure.
        """
        key = (text(atlas.get("project_code")).upper(), text(atlas.get("sage_third_party_code")).upper(),
               atlas.get("fiscal_year"), text(atlas.get("sage_bap_number")).upper())
        other = (entry.get("project_code"), entry.get("third_party"), entry.get("fiscal_year"),
                 text(entry.get("matching_reference")).upper())
        amount, total = money(atlas.get("total_project_charges")), money(entry.get("amount"))
        if (not all(v not in (None, "") for v in key) or key != other
                or not entry.get("identity_complete") or not entry.get("ref")
                or atlas.get("bap_status") != "Envoyé SAGE"
                or amount is None or total is None or amount * total < 0 or abs(amount - total) > Decimal("0.01")):
            raise ValueError("Preuve fuzzy incomplète ou projet/tiers/exercice/BAP/montant incompatible")
        unknown = (*key[:3], "")
        left = self._near(self.atlas, key, total) + self._near(self.atlas, unknown, total)
        right = self._near(self.sage, key, amount) + self._near(self.sage, unknown, amount)
        if (len(left) != 1 or len(right) != 1 or left[0].get("source_id") != atlas.get("source_id")
                or right[0].get("ref") != entry["ref"]):
            raise ValueError("Correspondance fuzzy non unique dans les deux sens")
