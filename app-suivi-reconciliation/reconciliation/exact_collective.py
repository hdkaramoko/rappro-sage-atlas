"""Autorisation Exact multilignes, atomique et fondée sur une bijection réelle."""

from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from reconciliation_contract import entry_from_sage, money
from reconciliation_contract.exact_assignment import exact_bijection

from .business import LOCAL_BUSINESS_REVIEW_REASON
from .models import LineReview
from .review import FIELDS, decide, is_current, signature
from .validation_evidence import exact_group_signature


def atlas_source(frozen):
    """Projette la source photographiée vers les noms du contrat pur, sans réécriture."""
    return {column: frozen.source.get(field) for column, field in {
        "Id": "source_id", "Code projet": "project_code", "Année": "fiscal_year",
        "Code tiers SAGE": "sage_third_party_code", "N° BAP (SAGE)": "sage_bap_number",
        "Libellé ATLAS": "atlas_label", "Total charges projet (€)": "total_project_charges",
        "Date comptable": "accounting_date", "N° pièce SAGE": "sage_document_number", "Devise": "currency"}.items()}


def validate_exact_group(campaign, rows, external_refs):
    """Prépare puis confirme tout le groupe Exact dans le savepoint de l'appelant.

    `rows` fournit toutes les photographies du groupe ; `external_refs` les preuves
    revendiquées par d'autres groupes. Autorisations v3, sources, bijection, totaux,
    priorités humaines et réservations sont revérifiés. Chaque decide conserve son
    montant individuel, sa preuve et son audit. Toute erreur annule tout le groupe.
    Retourne None ; ValidationError si une précondition comptable échoue.
    """
    group = rows[0].line.group
    if len(rows) != group.lines.count() or group.match_status != "MATCHED" or len(group.evidence) != 1:
        raise ValidationError("Composition Exact incomplète")
    for frozen in rows:
        line = frozen.line
        if (frozen.group.data.get("auto_validation") != {"source": "AUTO", "rule": "MATCH_EXACT", "state": "VALIDATED"}
                or LOCAL_BUSINESS_REVIEW_REASON in frozen.reasons or line.version and line.validation_source == "MANUAL"
                or line.inventory_link_id or line.adjustment_version or line.manual_assignment):
            raise ValidationError("Autorisation Exact absente ou décision humaine prioritaire")
    proofs = [r for c in group.evidence for r in c.get("rows", [])]
    try:
        mapping = exact_bijection([atlas_source(row) for row in rows], proofs)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if any(e["ref"] in external_refs for e in mapping.values()):
        raise ValidationError("Écriture Exact revendiquée par un autre groupe")
    if group.sage_total is None or abs(sum(money(e["amount"]) for e in mapping.values())-group.sage_total) > Decimal("0.01"):
        raise ValidationError("Total de groupe Exact incohérent")
    # Vérifie les preuves de contrôle en une lecture avant toute décision.
    from reconciliation_contract import control_identity, digest
    keys = {digest(control_identity(e, sage=True)) for e in mapping.values()}
    controls = {c.key: c for c in campaign.controls.filter(key__in=keys)}
    for entry in mapping.values():
        control = controls.get(digest(control_identity(entry, sage=True)))
        if not control or entry not in control.data["entries"]:
            raise ValidationError("Écriture Exact absente du contrôle de campagne")
    assignments = {row.line_id: {"kind": "EXACT_GROUP", "group_signature": exact_group_signature(group),
                   "entry": mapping[row.source["source_id"]]} for row in rows}
    if all(row.line.state == "VALIDATED" and row.line.validation_source == "AUTO"
           and row.line.automatic_assignment == assignments[row.line_id] and is_current(row.line) for row in rows):
        return
    for frozen in sorted(rows, key=lambda row: row.source["source_id"]):
        line = LineReview.objects.select_related("transaction__project", "group", "campaign", "inventory_link").get(pk=frozen.line_id)
        entry = assignments[line.pk]["entry"]
        values = {name: {"mode": "KEEP"} for name in FIELDS}
        values.update(status={"mode": "SET", "value": "Comptabilisé"},
                      amount={"mode": "SET", "value": str(line.transaction.total_project_charges)},
                      document={"mode": "SET", "value": entry["document"]}, date={"mode": "SET", "value": entry["date"]})
        result = decide(line.pk, None, state="VALIDATED", values=values, comment="Validation automatique — bijection Exact du groupe",
               expected_version=line.version, expected_group_version=line.group.version, expected_source=signature(line),
               _automatic=True, _automatic_assignment=assignments[line.pk])
        frozen.fingerprint = signature(result)
        frozen.save(update_fields=["fingerprint"])


def apply_exact_groups(campaign, *, progress=None):
    """Traite les groupes Exact v3 multilignes avant les autorisations individuelles.

    Précharge seulement les photographies des groupes multilignes et parcourt les
    revendications par lots ; un savepoint par groupe
    garantit zéro validation partielle. Les refus utilisent l'audit existant et ne
    touchent pas aux décisions humaines. Retourne les ids traités pour éviter tout
    repli individuel ultérieur. Appel réservé à l'import d'une nouvelle campagne.
    """
    if campaign.metadata.get("schema_version") != 3 or campaign.metadata.get("validation_policy") != "confirmed-exact-v2":
        return set()
    targets = list(campaign.reviews.filter(line__group__rule="MATCH_EXACT").values("line__group_id").annotate(
        members=Count("pk")).filter(members__gt=1).values_list("line__group_id", flat=True))
    if not targets:
        return set()
    rows = list(campaign.reviews.filter(line__group_id__in=targets).select_related(
        "group", "line__transaction__project", "line__group", "line__campaign", "line__inventory_link"))
    groups, owners = defaultdict(list), defaultdict(set)
    for frozen in rows:
        groups[frozen.line.group_id].append(frozen)
    claims = campaign.reviews.order_by().values_list("line__group_id", "group__data").distinct()
    for owner, data in claims.iterator(chunk_size=100):
        for candidate in data.get("evidence", []):
            for raw in candidate.get("rows", []):
                owners[entry_from_sage(raw)["ref"]].add(owner)
    handled = set()
    for group_id, members in sorted(groups.items(), key=lambda item: item[1][0].group.key):
        if len(members) < 2 or members[0].group.data["rule"] != "MATCH_EXACT":
            continue
        handled.update(row.line_id for row in members)
        external = {ref for ref, claimants in owners.items() if claimants - {group_id}}
        try:
            with transaction.atomic():
                validate_exact_group(campaign, members, external)
        except ValidationError as exc:
            from .collective_validation import reject_piece
            reject_piece(campaign, members, exc.messages)
        if progress:
            progress("Groupes Exact examinés", len(handled))
    return handled
