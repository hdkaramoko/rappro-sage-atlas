"""Extension v3 explicite : inventaire Sage et contrôle consolidé sans dépendances."""

from decimal import Decimal
from typing import Iterable

from . import ODS, control_identity, digest, entry_from_sage, label, money, snapshot, text, year_of

CAPABILITY = "sage_inventory_v1"


def ods_scope(row: dict, *, sage: bool = False) -> str:
    """Retourne l'empreinte projet/exercice/tiers ODS ou une chaîne vide.

    Permet de compter en SQL les candidats concurrents avec un autre libellé
    sans charger toutes les pièces. Aucune donnée n'est modifiée.
    """
    identity = control_identity(row, sage=sage)
    return digest(identity["parts"][:3]) if identity["strategy"] == ODS else ""


def exclusion_policy(prefixes: Iterable[str] = ()) -> dict:
    """Valide des préfixes de trois caractères et retourne leur politique signée.

    `prefixes` est une séquence de chaînes, jamais une chaîne CSV. Les espaces
    externes et la casse sont normalisés ; une valeur invalide lève ValueError.
    La liste vide rend tous les types éligibles. Aucun effet de bord.
    """
    if isinstance(prefixes, (str, bytes)) or not isinstance(prefixes, (list, tuple, set)):
        raise ValueError("Les exclusions Sage doivent être une liste de préfixes")
    normalized = []
    for prefix in prefixes:
        if not isinstance(prefix, str):
            raise ValueError("Chaque préfixe Sage doit être une chaîne")
        value = prefix.strip().upper()
        if len(value) != 3 or not value.isascii() or not value.isalnum():
            raise ValueError("Chaque préfixe Sage doit contenir trois caractères alphanumériques")
        normalized.append(value)
    data = {"version": 1, "prefixes": sorted(set(normalized))}
    return {**data, "signature": digest(data)}


def inventory_record(entry: dict, policy: dict, *, source_fingerprint: str | None = None,
                     attributes: dict | None = None) -> dict:
    """Signe une écriture canonique Sage et sa raison d'exclusion historique.

    L'identité technique `ref` reste celle du v3 ; `record_id` identifie le
    contenu de la photographie et son empreinte source avant typage si fournie.
    `attributes` conserve les références/comptes utiles hors contrat v3.
    Deux contenus ayant la même ref sont conservés
    mais rendront le contrôle indéterminé. Une pièce absente reste éligible.
    Les montants sont des chaînes décimales EUR ou None, jamais des flottants.
    """
    prefix = entry["document"][:3]
    excluded = prefix in policy["prefixes"]
    source_fingerprint = source_fingerprint or digest(entry)
    attributes = attributes or {}
    data = {"entry": entry, "source_fingerprint": source_fingerprint, "attributes": attributes,
            "record_id": digest([entry, source_fingerprint, attributes]), "document_type": prefix,
            "control_key": digest(control_identity(entry, sage=True)),
            "eligible": not excluded,
            "exclusion_reason": f"Préfixe {prefix} exclu" if excluded else ""}
    return {**data, "signature": digest(data)}


def validate_inventory_record(data: dict, policy: dict) -> dict:
    """Revalide contenu, référence et signature ; lève ValueError si altérés.

    Le serveur recalcule la clé technique, la complétude et la politique ;
    les montants EUR signés sont admis jusqu'à neuf décimales sans arrondi.
    Aucune décision ni mutation de base n'est réalisée ici.
    """
    if not isinstance(data, dict) or not isinstance(data.get("entry"), dict):
        raise ValueError("Écriture Sage mal formée")
    entry = data["entry"]
    fingerprint = data.get("source_fingerprint")
    attributes = data.get("attributes")
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in fingerprint)
            or not isinstance(attributes, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in attributes.items())):
        raise ValueError("Empreinte source ou attributs Sage invalides")
    fields = ("project_code", "document", "date", "journal", "line", "analytic_line",
              "third_party", "label", "original_label", "currency", "ref")
    if any(not isinstance(entry.get(k), str) for k in fields):
        raise ValueError("Champ texte Sage invalide")
    if entry.get("fiscal_year") != year_of(entry["date"]):
        raise ValueError("Exercice Sage incohérent")
    identity = [entry[k] for k in ("project_code", "fiscal_year", "document", "journal", "line", "analytic_line")]
    if entry["ref"] != digest(identity) or entry.get("identity_complete") is not all(v not in (None, "") for v in identity):
        raise ValueError("Identité Sage incohérente")
    amount = entry.get("amount")
    if amount is not None and (not isinstance(amount, str) or money(amount) is None or money(amount).as_tuple().exponent < -9):
        raise ValueError("Montant Sage invalide (neuf décimales maximum)")
    canonical = entry_from_sage({
        "Projet": entry["project_code"], "Numéro pièce": entry["document"],
        "Date comptable": entry["date"], "Journal": entry["journal"],
        "N° de ligne comptable": entry["line"], "N° de ligne Analytique": entry["analytic_line"],
        "Code Tiers - Tiers doc Orig": entry["third_party"], "Libellé pièce": entry["original_label"],
        "Devise": entry["currency"], "Charges (Dépenses)": amount})
    if entry != canonical:
        raise ValueError("Écriture Sage non canonique")
    if data != inventory_record(entry, policy, source_fingerprint=fingerprint, attributes=attributes):
        raise ValueError("Signature ou exclusion Sage incohérente")
    return data


def consolidate(identity: dict, atlas: list[dict], records: list[dict],
                allocations: list[dict], *, amount_field: str = "total_sage_charges",
                tolerance: str = "0.01", scope_reasons: Iterable[str] = (), manual_ods: bool = False) -> dict:
    """Calcule les états Comptabilisé et global pour une seule clé métier.

    Standard : projet/exercice/pièce ; ODS : projet/exercice/tiers/libellé
    normalisé. `atlas` contient uniquement les sources Comptabilisé ; les
    `allocations` portent montant individuel EUR, refs et fraîcheur validée.
    La tolérance est en euros (défaut un centime), les signes sont préservés.
    Les montants absents, identités partagées et allocations ambiguës rendent
    le résultat INDETERMINE. Une proposition non confirmée ne contribue pas.
    Le libellé ODS des nouvelles sources Comptabilisé vient de Libellé SAGE.
    L'exception sans libellé en un-pour-un fiable reste réservée aux anciennes
    sources, où le champ canonique sage_label était absent.
    `manual_ods` autorise seulement la résolution explicitement confirmée par
    l'application de preuves ODS identifiées ; elle ne crée jamais d'auto-validation.
    Retourne un dictionnaire signé sans aucun effet de bord.
    `individual_tolerance_verified` est une attestation serveur ciblée des nouvelles
    affectations Confirmé/Exact : une seule écriture signée peut différer du montant
    réservé de la tolérance, sans autoriser de fraction ni contourner l'unicité.
    Les charges comparées sont déjà en EUR : les devises d'origine Atlas et Sage
    ne provoquent ni conversion supplémentaire ni anomalie à elles seules.
    """
    if money(tolerance) is None or money(tolerance) < 0:
        raise ValueError("Tolérance invalide")
    entries = [r["entry"] for r in records]
    excluded = [r for r in records if not r["eligible"]]
    reasons = list(scope_reasons)
    if excluded and len(excluded) != len(records):
        reasons.append("Groupe partiellement exclu")
    if any(control_identity(e, sage=True) != identity for e in entries):
        reasons.append("Écriture hors du groupe")
    if any(control_identity(a) != identity for a in atlas):
        reasons.append("Source Atlas hors du groupe")
    atlas_ids = [(a.get("project_code"), a.get("fiscal_year"), a.get("source_id")) for a in atlas]
    if len(atlas_ids) != len(set(atlas_ids)) or any(not a[-1] for a in atlas_ids):
        reasons.append("Identité Atlas absente ou répétée")
    # Les deux sources exposent des colonnes de charges EUR ; leur devise
    # d'opération n'est pas l'unité de ces montants et ne justifie pas un veto.
    if identity["strategy"] == ODS:
        # Une somme de plusieurs opérations ne démontre pas leur unicité.
        if not manual_ods and (len(atlas) != 1 or len(entries) != 1):
            reasons.append("Unicité économique ODS/ODG non démontrée")
        for e in entries:
            prefix, journal = e["document"][:3], e["journal"]
            if journal in ("ODS", "ODG") and prefix != journal:
                reasons.append("Désaccord préfixe/journal ODS/ODG")
    checked_identity = identity
    missing_label_unique = (identity["strategy"] == ODS and not identity["parts"][-1]
                            and all(v not in (None, "") for v in identity["parts"][:-1])
                            and len(atlas) == len(entries) == 1
                            and "sage_label" not in atlas[0]
                            and not label(atlas[0].get("atlas_label")) and not label(entries[0]["label"]))
    if missing_label_unique or (manual_ods and identity["strategy"] == ODS and not identity["parts"][-1]
                               and all(v not in (None, "") for v in identity["parts"][:-1])):
        checked_identity = {**identity, "parts": [*identity["parts"][:-1], "<libellé absent unique>"]}
    source = snapshot(checked_identity, atlas, entries, amount_field=amount_field,
                      tolerance=tolerance, reasons=reasons)
    # La clé publiée reste la véritable clé composite, sans libellé inventé.
    base_reasons = source["reasons"]
    confirmed, consumed, line_ids = [], set(), set()
    allocation_reasons = []
    available = {e["ref"]: e for e in entries}
    for allocation in allocations:
        if not allocation.get("validated") or not allocation.get("current") or allocation.get("source_status") != "Envoyé SAGE":
            continue
        refs = allocation.get("refs", [])
        line_id = allocation.get("line_key")
        amount = money(allocation.get("amount"))
        if (not line_id or line_id in line_ids or not refs or len(refs) != len(set(refs))
                or consumed.intersection(refs) or any(ref not in available for ref in refs)):
            allocation_reasons.append("Affectation répétée, partagée ou sans preuve Sage")
            continue
        line_ids.add(line_id)
        consumed.update(refs)
        if amount is None or any(money(available[ref]["amount"]) is None for ref in refs):
            allocation_reasons.append("Montant d'affectation absent")
            continue
        evidence_total = sum((money(available[ref]["amount"]) for ref in refs), Decimal(0))
        partial = (allocation.get("partial_validated") is True and len(refs) == 1
                   and amount * evidence_total >= 0 and abs(amount) <= abs(evidence_total))
        tolerated = (allocation.get("individual_tolerance_verified") is True and len(refs) == 1
                     and amount * evidence_total >= 0 and abs(evidence_total - amount) <= money(tolerance))
        if evidence_total != amount and not partial and not tolerated:
            allocation_reasons.append("Répartition partielle ou plusieurs-vers-plusieurs non démontrée")
            continue
        confirmed.append({**allocation, "amount": str(amount)})
    if identity["strategy"] == ODS and confirmed and not manual_ods:
        allocation_reasons.append("Affectation Envoyé SAGE ODS/ODG à examiner")
    source_total, sage_total = money(source["atlas_total"]), money(source["sage_total"])
    sent_total = sum((money(a["amount"]) for a in confirmed), Decimal(0))
    global_gap = source_total + sent_total - sage_total if source_total is not None and sage_total is not None else None
    initial_gap = source_total - sage_total if source_total is not None and sage_total is not None else None
    initial_state = "INDETERMINE" if base_reasons else "EQUILIBRE" if abs(initial_gap) <= money(tolerance) else "ECART"
    global_reasons = sorted(set(base_reasons + allocation_reasons))
    # Les compensations charge/avoir ne peuvent pas masquer une ambiguïté.
    amounts = [money(a.get(amount_field)) for a in atlas] + [money(e["amount"]) for e in entries] + [money(a["amount"]) for a in confirmed]
    if any(a is not None and a < 0 for a in amounts) and any(a is not None and a > 0 for a in amounts):
        global_reasons = sorted(set(global_reasons + ["Signes mixtes à examiner"]))
    state = "INDETERMINE" if global_reasons else "EQUILIBRE" if abs(global_gap) <= money(tolerance) else "ECART"
    if records and len(excluded) == len(records):
        initial_state = state = "EXCLU"
        global_reasons = sorted({r["exclusion_reason"] for r in excluded})
    data = {"version": 1, "identity": identity, "key": digest(identity),
            "accounted_state": initial_state, "state": state,
            "accounted_total": str(source_total) if source_total is not None else None,
            "sage_total": str(sage_total) if sage_total is not None else None,
            "confirmed_sent_total": str(sent_total),
            "accounted_gap": str(initial_gap) if initial_gap is not None else None,
            "gap": str(global_gap) if global_gap is not None else None,
            "accounted_reasons": base_reasons, "reasons": global_reasons,
            "atlas_ids": [list(v) for v in atlas_ids], "sage_refs": sorted(e["ref"] for e in entries),
            "confirmed_allocations": confirmed, "atlas_count": len(atlas), "sage_count": len(entries),
            "auto_validated": initial_state == "EQUILIBRE" and bool(atlas) and not manual_ods,
            "amount_field": amount_field, "tolerance": tolerance}
    return {**data, "signature": digest(data)}
