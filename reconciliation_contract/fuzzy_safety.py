"""Preuve bilatérale des AUTO structurées, indépendante du score et du classement."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from decimal import Decimal

from . import money, text

FUZZY_RULES = frozenset({"MATCH_FUZZY_HIGH", "MATCH_FUZZY_REVIEW"})
STRUCTURED_RULES = FUZZY_RULES | {"MATCH_WITHOUT_LABEL", "MATCH_BAP", "MATCH_INDIVIDUAL"}
INDIVIDUAL_RULES = STRUCTURED_RULES | {"MATCH_EXACT"}


class FuzzySafety:
    """Indexe les sources complètes pour prouver une unicité dans les deux sens.

    Les itérables canoniques Atlas/Sage sont consommés une seule fois. Les
    doublons sont conservés : ils interdisent une preuve individuelle certaine.
    La recherche par projet/tiers/exercice/BAP puis montant évite un produit croisé.
    Aucun effet de bord externe, aucune conversion de devise ni comparaison fuzzy.
    """

    def __init__(self, atlas, sage, *, precise_atlas=None):
        """Construit les index triés et un catalogue des identités Sage en un passage.

        Seuls Comptabilisé et Envoyé SAGE peuvent concurrencer une réservation.
        Les sources incomplètes ne deviennent jamais des candidats autorisés.
        `precise_atlas` alimente le seul index résiduel exact ; les autres règles
        conservent l'index historique pour ne pas modifier leurs résultats.
        """
        self.atlas = self._index(atlas, sage=False)
        self._documents = defaultdict(list)
        self._references = defaultdict(int)
        self.sage = self._index(self._catalogue(sage), sage=True)
        self.precise_atlas = self._index(precise_atlas, sage=False) if precise_atlas is not None else self.atlas
        self._bap_balances = {}

    def _catalogue(self, rows):
        """Indexe une seule fois les pièces et occurrences d'identité Sage."""
        for row in rows:
            key = (text(row.get("project_code")).upper(), row.get("fiscal_year"),
                   text(row.get("document")).upper())
            self._documents[key].append(row)
            if row.get("ref"):
                self._references[row["ref"]] += 1
            yield row

    def _distinct_accounted(self, row, entry, tolerance):
        """Écarte une comptabilisée seulement sur preuve Sage unique et distincte.

        La pièce, le tiers, la date et le montant doivent désigner une écriture
        complète sans doublon d'identité. Toute information ambiguë bloque.
        """
        if row.get("bap_status") != "Comptabilisé":
            return False
        document = text(row.get("sage_document_number")).upper()
        date = text(row.get("accounting_date"))
        amount = money(row.get("total_sage_charges"))
        if not document or not date or amount is None:
            return False
        key = (text(row.get("project_code")).upper(), row.get("fiscal_year"), document)
        matches = []
        for candidate in self._documents.get(key, ()):
            total = money(candidate.get("amount"))
            if total is None:
                return False
            if total * amount >= 0 and abs(total - amount) <= tolerance:
                matches.append(candidate)
        if len(matches) != 1:
            return False
        candidate = matches[0]
        return bool(candidate.get("identity_complete") and candidate.get("ref")
                    and self._references[candidate["ref"]] == 1
                    and candidate["ref"] != entry["ref"]
                    and text(candidate.get("date")) == date
                    and text(candidate.get("third_party")).upper()
                    == text(row.get("sage_third_party_code")).upper())

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
    def _near(index, key, amount, tolerance=Decimal("0.01"), *, exclude=None):
        """Retourne au plus deux occurrences compatibles après exclusions prouvées.

        Paramètres : index privé, clé, Decimal fini et seuil explicite. Sans effet
        de bord ; aucune exception métier n'est masquée.
        Le filtre facultatif s'applique avant la limite de deux occurrences.
        """
        amounts, rows = index.get(key, ([], []))
        start = bisect_left(amounts, amount - tolerance)
        end = bisect_right(amounts, amount + tolerance)
        matches = []
        for position in range(start, end):
            if amounts[position] * amount >= 0 and not (exclude and exclude(rows[position])):
                matches.append(rows[position])
                if len(matches) == 2:
                    break
        return matches

    def verify(self, atlas, entry, *, tolerance=Decimal("0.01"), precise=False, distinct_accounted=False):
        """Vérifie une paire canonique ; retourne None ou lève ValueError motivée.

        Exige projet/tiers/exercice identiques, montant signé au centime,
        référence Sage complète, même BAP et unicité bilatérale sur ce périmètre.
        Les devises d'origine n'interviennent pas : les charges sont déjà en EUR.
        Un concurrent sans BAP reste potentiellement concurrent et bloque l'AUTO.
        Ni le score ni le libellé ne départagent les concurrents. Lecture pure.
        `precise` choisit les sources exactes pour les seuls recours ; `tolerance`
        est le seuil vérifié de la règle, pas celui du contrôle comptable.
        `distinct_accounted` réserve aux libellés proches et au BAP l'exclusion prouvée
        des comptabilisées ; les autres catégories gardent leur comportement.
        """
        key = (text(atlas.get("project_code")).upper(), text(atlas.get("sage_third_party_code")).upper(),
               atlas.get("fiscal_year"), text(atlas.get("sage_bap_number")).upper())
        other = (entry.get("project_code"), entry.get("third_party"), entry.get("fiscal_year"),
                 text(entry.get("matching_reference")).upper())
        amount, total = money(atlas.get("total_project_charges")), money(entry.get("amount"))
        if (not all(v not in (None, "") for v in key) or key != other
                or not entry.get("identity_complete") or not entry.get("ref")
                or atlas.get("bap_status") != "Envoyé SAGE"
                or amount is None or total is None or amount * total < 0 or abs(amount - total) > tolerance):
            raise ValueError("Preuve structurée incomplète ou projet/tiers/exercice/BAP/montant incompatible")
        unknown = (*key[:3], "")
        index = self.precise_atlas if precise else self.atlas
        exclude = (lambda row: self._distinct_accounted(row, entry, tolerance)) if distinct_accounted else None
        left = (self._near(index, key, total, tolerance, exclude=exclude)
                + self._near(index, unknown, total, tolerance, exclude=exclude))
        right = self._near(self.sage, key, amount, tolerance) + self._near(self.sage, unknown, amount, tolerance)
        if (len(left) != 1 or len(right) != 1 or left[0].get("source_id") != atlas.get("source_id")
                or right[0].get("ref") != entry["ref"]):
            raise ValueError("Correspondance non unique dans les deux sens")

    def verify_bap_balance(self, atlas, entry, *, tolerance=Decimal("0.01"), precise=False, distinct_accounted=True):
        """Vérifie la paire et l'équilibre complet de son BAP avant AUTO BAP.

        Les index proviennent des populations complètes, pas des seuls candidats
        retenus. Exige même nombre de lignes et sommes signées à 0,01 EUR près.
        Retourne None ; ValueError si l'ensemble ne prouve pas une bijection.
        Aucun effet de bord ; les réservations restent contrôlées par Django.
        Le seuil explicite porte sur chaque paire ET la somme complète ; le
        cache local inclut le seuil et la précision, sans tolérance cumulée.
        Écarte les comptabilisées seulement sur preuve d'écriture Sage distincte,
        avec le même mécanisme que Libellé proche ; aucun autre contrôle n'est levé.
        """
        self.verify(atlas, entry, tolerance=tolerance, precise=precise, distinct_accounted=distinct_accounted)
        key = (text(atlas.get("project_code")).upper(), text(atlas.get("sage_third_party_code")).upper(),
               atlas.get("fiscal_year"), text(atlas.get("sage_bap_number")).upper())
        cache_key = (key, tolerance, precise)
        if cache_key not in self._bap_balances:
            index = self.precise_atlas if precise else self.atlas
            left, right = index.get(key, ([], []))[0], self.sage.get(key, ([], []))[0]
            self._bap_balances[cache_key] = len(left) == len(right) and abs(sum(left, Decimal(0)) - sum(right, Decimal(0))) <= tolerance
        if not self._bap_balances[cache_key]:
            raise ValueError("BAP non équilibré ou bijection complète non démontrée")

    def verify_individual(self, atlas, entry, *, tolerance=Decimal("0.01"), precise=False):
        """Vérifie un recours individuel sans contourner l'écart global d'un BAP complet.

        Un vrai sous-ensemble individuel reste possible. Si le bloc complet
        possède une bijection, chaque petite différence ne peut cumuler au-delà
        du seuil global. Cache local ; ValueError refuse AUTO sans aucune écriture.
        """
        self.verify(atlas, entry, tolerance=tolerance, precise=precise)
        if not precise:
            return
        key = (text(atlas.get("project_code")).upper(), text(atlas.get("sage_third_party_code")).upper(),
               atlas.get("fiscal_year"), text(atlas.get("sage_bap_number")).upper())
        cache_key = (key, tolerance, "individual_total")
        if cache_key not in self._bap_balances:
            left, right = self.precise_atlas.get(key, ([], []))[0], self.sage.get(key, ([], []))[0]
            complete = len(left) == len(right) and bool(left)
            if complete and abs(sum(left, Decimal(0)) - sum(right, Decimal(0))) > tolerance:
                complete = all(len(self._near(self.sage, key, value, tolerance)) == 1 for value in left)
                complete = complete and all(len(self._near(self.precise_atlas, key, value, tolerance)) == 1 for value in right)
                self._bap_balances[cache_key] = not complete
            else:
                self._bap_balances[cache_key] = True
        if not self._bap_balances[cache_key]:
            raise ValueError("Écart global du BAP supérieur à la tolérance : arbitrage requis")
