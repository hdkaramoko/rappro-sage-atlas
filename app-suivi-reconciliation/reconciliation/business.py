"""Actions métier Lot 2 : corrections et liens d'inventaire, atomiques et audités."""

from contextvars import ContextVar
from decimal import Decimal
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from reconciliation_contract import digest, money, text
from reconciliation_contract.sage_inventory import CAPABILITY

from .models import (AtlasAdjustment, Campaign, CampaignAction, CampaignGlobalControl,
                     CampaignInventory, CampaignReview, CampaignSageEntry, ControlContribution,
                     LineReview, ManualAllocation, ManualReconciliation, ReviewEvent)

IMPORTING = ContextVar("lot2_importing", default=False)
LOCAL_BUSINESS_REVIEW_REASON = "Correction ou rapprochement manuel local à la campagne précédente : nouvelle confirmation requise"


def source_amount(inventory: CampaignInventory) -> Decimal | None:
    """Retourne la charge individuelle EUR source sans mutation ni conversion float.

    Comptabilisé suit la politique de campagne ; Confirmé suit les charges Sage
    Atlas (preuve locale pièce/date/montant), les autres Envoyé les charges projet.
    Une absence reste None, jamais zéro. Aucun effet de bord.
    """
    data = inventory.data
    field = "total_project_charges"
    if data.get("bap_status") == "Comptabilisé":
        field = inventory.campaign.metadata.get("amount_field") or "total_sage_charges"
    elif data.get("sage_document_number") and data.get("accounting_date") and money(data.get("total_sage_charges")) is not None:
        field = "total_sage_charges"
    return money(data.get(field))


def retained_amount(inventory: CampaignInventory) -> Decimal | None:
    """Retourne le montant métier EUR retenu, distinct du montant source immuable.

    Une correction active AMOUNT fournit son Decimal à deux décimales ; DUPLICATE
    retient zéro comme exclusion explicite. Une annulation rend la valeur source.
    Peut charger la relation adjustment si elle n'est pas préchargée ; aucune écriture.
    """
    adjustment = getattr(inventory, "adjustment", None)
    if adjustment and adjustment.active:
        return Decimal(0) if adjustment.reason == AtlasAdjustment.Reason.DUPLICATE else adjustment.amount
    return source_amount(inventory)


def adjustment_version(inventory: CampaignInventory) -> int:
    """Retourne la version de correction, même annulée, ou zéro en son absence.

    Une annulation exige aussi une réévaluation de la confirmation précédente.
    Lecture seule de l'objet/relation de la ligne exacte de campagne.
    """
    adjustment = getattr(inventory, "adjustment", None)
    return adjustment.version if adjustment else 0


def contribution_is_current(contribution, inventory=None) -> bool:
    """Vérifie qu'une réservation historique consomme encore réellement Sage.

    Retourne False pour un doublon exclu, une correction non reconfirmée, un
    lien d'inventaire séparé ou une décision périmée/refusée. `inventory` peut
    être préchargé pour éviter les N+1 ; sinon une lecture indexée est effectuée.
    Aucun effet de bord ni libération silencieuse de la décision historique.
    """
    from .review import is_current
    line = contribution.line
    if line.inventory_link_id or line.state != "VALIDATED" or not is_current(line):
        return False
    if inventory is None:
        inventory = CampaignInventory.objects.filter(campaign_id=contribution.control.campaign_id,
            business_key=line.transaction.business_key, present=True).select_related("adjustment").first()
    if inventory is None:
        return False
    correction = getattr(inventory, "adjustment", None)
    return (adjustment_version(inventory) == line.adjustment_version
            and not (correction and correction.active and correction.reason == AtlasAdjustment.Reason.DUPLICATE))


def line_for(inventory: CampaignInventory):
    """Charge la projection de revue de cette ligne/campagne ou retourne None.

    L'identité indexée business_key évite une recherche globale dans le JSON.
    Une ligne Comptabilisé peut légitimement n'avoir aucune LineReview.
    """
    return LineReview.objects.filter(campaign=inventory.campaign, transaction__business_key=inventory.business_key).select_related(
        "group", "campaign", "transaction__project", "inventory_link").first()


def affected_keys(inventory: CampaignInventory) -> set[str]:
    """Retourne les clés source et toutes les cibles actuellement affectées.

    Sert avant ET après une action pour recalculer aussi les anciennes pièces.
    Lecture indexée limitée à la ligne ; aucune décision n'est modifiée.
    """
    keys = {inventory.control_key} if inventory.control_key else set()
    keys.update(ManualAllocation.objects.filter(link__inventory=inventory, active=True).values_list("entry__control_key", flat=True))
    keys.update(ControlContribution.objects.filter(control__campaign=inventory.campaign,
                line__transaction__business_key=inventory.business_key).values_list("control__key", flat=True))
    return keys


def recalculate(campaign: Campaign, keys: set[str]) -> dict:
    """Actualise synchroniquement les seuls contrôles `keys` dans la transaction métier.

    Réutilise campaign_controls du Lot 1 et conserve `data` initial intact. Les
    contrôles sont verrouillés en ordre stable ; un calcul identique n'incrémente
    pas sa version. Retourne {clé: signature courante}. Les anciens fichiers sans
    inventaire Sage n'ont pas de faux zéro : retourne {} (UI indisponible).
    Le circuit d'import suspend ce hook pendant ses auto-validations initiales.
    Les synthèses de cadrage déjà préparées sont ensuite actualisées pour les
    seuls projets touchés ; aucune ancienne campagne n'est reconstruite.
    """
    if IMPORTING.get() or CAPABILITY not in campaign.metadata.get("capabilities", []) or not keys:
        return {}
    from .global_control import campaign_controls
    rows = {c.key: c for c in campaign.global_controls.select_for_update().filter(key__in=keys).order_by("key")}
    result = {}
    projects = {row.project_code for row in rows.values()}
    for data in campaign_controls(campaign, keys=sorted(keys)):
        projects.add(data["identity"]["parts"][0])
        row = rows.get(data["key"])
        if row is None:
            row = CampaignGlobalControl.objects.create(campaign=campaign, key=data["key"],
                project_code=data["identity"]["parts"][0], state=data["state"], data=data)
        if (row.current_data or row.data) != data:
            row.current_data = data
            row.current_updated_at = timezone.now()
            row.current_version += 1
            row.save(update_fields=["current_data", "current_updated_at", "current_version"])
        result[row.key] = data["signature"]
    from .accounting import refresh_project
    from .accounting_models import AccountingProject
    for project in AccountingProject.objects.filter(campaign=campaign, project_code__in=projects).values_list("project_code", flat=True):
        refresh_project(campaign, project)
    return result


def _locked_inventory(pk: int, user) -> CampaignInventory:
    """Vérifie droits, publication et campagne courante sous verrou stable.

    Retourne la ligne avec correction préchargée. PermissionDenied interdit les
    projets hors portefeuille ; ValidationError signale une campagne close ou
    source absente. L'appelant doit être dans transaction.atomic.
    """
    from .campaign_views import projects_for
    entry = CampaignInventory.objects.select_related("campaign").get(pk=pk)
    if not user.is_authenticated or not user.is_active or not projects_for(user).filter(code=entry.project_code).exists():
        raise PermissionDenied
    campaign = Campaign.all_objects.select_for_update().get(pk=entry.campaign_id)
    if not campaign.is_current or not campaign.published or not entry.present:
        raise ValidationError("Cette campagne est close ou cette ligne absente. Actualisez la page.")
    entry = CampaignInventory.objects.select_for_update().get(pk=pk)
    entry.campaign = campaign
    return entry


def _request(inventory, request_id, payload, expected_version):
    """Valide version optimiste et idempotence d'une soumission autorisée.

    Retourne (UUID, empreinte, déjà_traitée). Un UUID réutilisé pour un autre
    contenu ou une version périmée lève ValidationError avant toute mutation.
    Les doublons identiques sont des lectures sans événement supplémentaire.
    """
    try:
        key = UUID(str(request_id)) if request_id else uuid4()
    except ValueError as exc:
        raise ValidationError("Identifiant de soumission invalide.") from exc
    fingerprint = digest(payload)
    previous = CampaignAction.objects.filter(request_id=key).first()
    if previous:
        if previous.inventory_id != inventory.pk or previous.request_hash != fingerprint:
            raise ValidationError("Cette soumission a déjà été utilisée pour une autre action.")
        return key, fingerprint, True
    if inventory.business_version != expected_version:
        raise ValidationError("Cette ligne a changé depuis son ouverture. Actualisez la page.")
    return key, fingerprint, False


def _snapshot(inventory) -> dict:
    """Photographie les valeurs métier et leurs versions pour l'audit sans altérer la source.

    Retourne des valeurs JSON portables (montants EUR en chaînes ou None).
    Les cibles sont des références réellement réservées avec pièce/date/montant,
    jamais une preuve moteur. Inclut les états chiffrés des contrôles impactés.
    """
    adjustment = getattr(inventory, "adjustment", None)
    link = getattr(inventory, "inventory_match", None)
    controls = {}
    for control in inventory.campaign.global_controls.filter(key__in=affected_keys(inventory)):
        data = control.current_data or control.data
        controls[control.key] = {name: data.get(name) for name in (
            "state", "accounted_state", "gap", "accounted_gap", "accounted_total", "confirmed_sent_total", "sage_total", "signature")}
    from .review import is_current
    line = line_for(inventory)
    return {"retained": str(retained_amount(inventory)) if retained_amount(inventory) is not None else None,
            "controls": controls,
            "decision": {"state": line.state, "version": line.version, "comment": line.comment,
                         "origin": line.validation_source, "current": is_current(line)} if line else None,
            "business_version": inventory.business_version,
            "adjustment": {"reason": adjustment.reason, "amount": str(adjustment.amount) if adjustment.amount is not None else None,
                           "active": adjustment.active, "version": adjustment.version, "comment": adjustment.comment} if adjustment else None,
            "link": manual_link_snapshot(link)}


def manual_link_snapshot(link) -> dict | None:
    """Retourne la preuve manuelle portable, ou None si aucun lien n'existe.

    Lit les allocations actives avec leurs écritures (une requête). Pièce,
    date, référence et montant EUR exact sont photographiés pour rendre lisibles
    remplacements, annulations et exports historiques, sans modifier les sources.
    """
    if link is None:
        return None
    allocations = [{"ref": a.entry.entry_ref, "record_id": a.entry.record_id,
                    "document": a.entry.document, "date": a.entry.data["entry"]["date"],
                    "amount": a.entry.data["entry"]["amount"]}
                   for a in link.allocations.filter(active=True).select_related("entry").order_by("pk")]
    return {"id": link.pk, "active": link.active, "version": link.version,
            "amount": str(link.amount), "comment": link.comment,
            "entries": [a["ref"] for a in allocations], "allocations": allocations}


def _finish(inventory, user, key, fingerprint, kind, before, keys):
    """Incrémente la révision métier, recalcule les anciennes/nouvelles cibles et audite.

    Appel interne atomique : retourne la ligne actualisée ; une erreur de calcul
    annule aussi correction/lien. Aucun événement n'est écrit pour un simple GET.
    """
    inventory.business_version += 1
    inventory.save(update_fields=["business_version"])
    inventory = CampaignInventory.objects.select_related("campaign", "adjustment", "inventory_match").get(pk=inventory.pk)
    signatures = recalculate(inventory.campaign, keys | affected_keys(inventory))
    after = {**_snapshot(inventory), "control_signatures": signatures, "actor_name": str(user) if user else "Automatique"}
    CampaignAction.objects.create(inventory=inventory, request_id=key, request_hash=fingerprint,
                                 kind=kind, before=before, after=after, actor=user)
    return inventory


@transaction.atomic
def correct_inventory(pk: int, user, *, reason: str = "", amount=None, comment: str = "",
                      cancel: bool = False, expected_version: int, request_id=None):
    """Crée/modifie/annule une correction locale de campagne et recalcule ses cibles.

    `amount` est un Decimal EUR à deux décimales, même signe que la source connue.
    DUPLICATE exclut explicitement la ligne (retenu zéro), sans effacer sa source.
    Une correction ne crée aucune confirmation ; les liens antérieurs deviennent
    à revoir si leur version de correction diffère. La fraîcheur de la décision
    touchée est invalidée sans remplacer son état/auteur. Retourne CampaignInventory.
    Droits, versions et UUID protègent les modifications ; toute erreur annule
    écritures, recalcul et événement dans la même transaction.
    """
    inventory = _locked_inventory(pk, user)
    value = money(amount)
    payload = {"kind": "CORRECTION", "reason": reason, "amount": str(value) if value is not None else None,
               "comment": comment.strip(), "cancel": cancel, "version": expected_version}
    key, fingerprint, done = _request(inventory, request_id, payload, expected_version)
    if done:
        return inventory
    adjustment = getattr(inventory, "adjustment", None)
    if not cancel:
        if reason not in AtlasAdjustment.Reason.values:
            raise ValidationError("Choisissez un motif de correction.")
        if reason == AtlasAdjustment.Reason.AMOUNT:
            if value is None or value.as_tuple().exponent < -2:
                raise ValidationError("Le montant corrigé doit être un montant EUR fini à deux décimales.")
            original = source_amount(inventory)
            if original is not None and original * value < 0:
                raise ValidationError("Le montant corrigé doit conserver le signe du montant source.")
        else:
            value = None
    if cancel and (adjustment is None or not adjustment.active):
        return inventory
    if adjustment and not cancel and adjustment.active and (adjustment.reason, adjustment.amount, adjustment.comment) == (reason, value, comment.strip()):
        return inventory
    before, keys = _snapshot(inventory), affected_keys(inventory)
    if adjustment is None:
        adjustment = AtlasAdjustment(inventory=inventory)
    else:
        adjustment.version += 1
    if not cancel:
        adjustment.reason, adjustment.amount = reason, value
    adjustment.active, adjustment.comment, adjustment.actor = not cancel, comment.strip(), user
    adjustment.save()
    line = line_for(inventory)
    if line:
        # L'état/auteur de la décision restent visibles ; seule sa fraîcheur est
        # invalidée par cette correction explicite, jamais réécrite en AUTO.
        from .campaigns import save_decision_snapshot
        line.source_signature = ""
        line.adjustment_version = adjustment.version
        line.version += 1
        line.save(update_fields=["source_signature", "version", "adjustment_version"])
        line.group.version += 1
        line.group.save(update_fields=["version"])
        save_decision_snapshot(line)
    return _finish(inventory, user, key, fingerprint, "CORRECTION_CANCEL" if cancel else "CORRECTION", before, keys)


def search_sage(inventory: CampaignInventory, user, filters: dict | None = None):
    """Recherche paginable dans l'inventaire Sage autorisé, jamais dans les candidats moteur.

    Filtre campagne/projet/exercice/éligibilité et propose pièce, tiers, montant,
    libellé. Toutes les charges comparées sont en EUR (politique Lot 1), même
    lorsque la devise d'opération Sage diffère. Lève PermissionDenied hors droits,
    ValidationError pour un ancien fichier/source incompatible ; aucune écriture.
    La devise d'origine Atlas ne restreint pas cette recherche en charges EUR.
    """
    from .campaign_views import projects_for
    if not user.is_authenticated or not user.is_active or not projects_for(user).filter(code=inventory.project_code).exists():
        raise PermissionDenied
    if not inventory.campaign.published or not inventory.present:
        raise ValidationError("Cette photographie n'est pas disponible pour la recherche.")
    if CAPABILITY not in inventory.campaign.metadata.get("capabilities", []):
        raise ValidationError("Contrôle global indisponible : cette campagne n'a pas d'inventaire Sage.")
    if inventory.data.get("bap_status") not in ("Comptabilisé", "Envoyé SAGE"):
        raise ValidationError("Le statut Atlas nécessite une revue avant rapprochement.")
    rows = inventory.campaign.sage_inventory.filter(project_code=inventory.project_code,
            fiscal_year=inventory.fiscal_year, eligible=True, data__entry__identity_complete=True)
    filters = filters or {}
    for field, lookup in (("document", "document__icontains"), ("third_party", "data__entry__third_party__icontains"), ("label", "data__entry__label__icontains")):
        if filters.get(field):
            rows = rows.filter(**{lookup: str(filters[field]).strip()})
    if filters.get("amount") not in (None, ""):
        value = money(filters["amount"])
        if value is None:
            raise ValidationError("Montant recherché invalide.")
        rows = rows.filter(amount=value)
    from django.db.models import Case, When, Value, IntegerField
    return rows.annotate(relevance=Case(When(amount=retained_amount(inventory), then=Value(0)), default=Value(1), output_field=IntegerField())).order_by("relevance", "document", "pk")


def selection_summary(inventory, user, entry_ids) -> dict:
    """Prévisualise des écritures entières et le montant retenu, sans confirmer.

    Les identifiants doivent être distincts, éligibles et univoques dans la campagne.
    Retourne entrées, sommes Decimal EUR et écart. ValidationError interdit les
    sélections hors périmètre, collisions ou montants manquants. Aucun effet de bord.
    """
    try:
        ids = [int(value) for value in entry_ids]
    except (ValueError, TypeError) as exc:
        raise ValidationError("Sélection Sage invalide.") from exc
    if not ids or len(ids) != len(set(ids)) or len(ids) > 100:
        raise ValidationError("Sélectionnez de une à cent écritures distinctes.")
    entries = list(search_sage(inventory, user).filter(pk__in=ids).order_by("pk"))
    if len(entries) != len(ids):
        raise ValidationError("Une écriture sélectionnée est exclue, absente ou hors du périmètre autorisé.")
    refs = [entry.entry_ref for entry in entries]
    collisions = inventory.campaign.sage_inventory.filter(entry_ref__in=refs).values("entry_ref").annotate(n=Count("pk")).filter(n__gt=1)
    if collisions.exists():
        raise ValidationError("L'identité d'une écriture Sage est ambiguë : contrôle manuel de la source requis.")
    amounts = [money(entry.data["entry"]["amount"]) for entry in entries]
    if any(amount is None for amount in amounts):
        raise ValidationError("Montant Sage absent : affectation impossible.")
    if any(v < 0 for v in amounts) and any(v > 0 for v in amounts):
        raise ValidationError("Une compensation charge/avoir ne peut pas être affectée automatiquement.")
    total, retained = sum(amounts, Decimal(0)), retained_amount(inventory)
    capacities, alerts = [], []
    for control in inventory.campaign.global_controls.filter(key__in={e.control_key for e in entries}):
        data = control.current_data or control.data
        accounted, sent, reference = (money(data[k]) for k in ("accounted_total", "confirmed_sent_total", "sage_total"))
        available = reference - accounted - sent if all(v is not None for v in (accounted, sent, reference)) else None
        capacities.append({"document": next(e.document for e in entries if e.control_key == control.key),
                           "accounted": accounted, "confirmed": sent, "available": available})
        if data["state"] in ("INDETERMINE", "EXCLU"):
            alerts.append("Un contrôle de la sélection est à revoir ou exclu ; aucune confirmation trompeuse ne sera autorisée.")
    if retained is None or abs(retained - total) > money(inventory.campaign.metadata["tolerance"]):
        alerts.append("La sélection ne correspond pas au montant retenu : corrigez-la avant confirmation.")
    return {"entries": entries, "sage_total": total, "retained": retained,
            "gap": retained - total if retained is not None else None, "capacities": capacities, "alerts": sorted(set(alerts))}


def _mirror_link(inventory, link, user, *, cancel=False):
    """Photographie la décision manuelle dans la revue existante sans fabriquer de candidat.

    Conserve rule/evidence moteur. Crée un ReviewEvent explicite d'origine
    INVENTORY_MANUAL, met à jour auteur/versions et libère les anciennes contributions.
    Une annulation rouvre la revue ; les sources et décisions historiques restent intactes.
    """
    from .review import signature, source_snapshot
    from .campaigns import save_decision_snapshot
    line = line_for(inventory)
    if line is None:
        return
    before = {"state": line.state, "values": line.values, "version": line.version}
    ControlContribution.objects.filter(control__campaign=inventory.campaign, line=line).delete()
    line.inventory_link = link
    line.adjustment_version = adjustment_version(inventory)
    line.validation_source, line.auto_validation_rule = "MANUAL", ""
    line.manual_assignment, line.automatic_assignment = [], {}
    line.state = "DRAFT" if cancel else "VALIDATED"
    if not cancel:
        first = link.allocations.filter(active=True).select_related("entry").order_by("pk").first().entry.data["entry"]
        line.values = {key: {"mode": "SET", "value": value} for key, value in {
            "amount": str(link.amount), "status": "Comptabilisé", "document": first["document"], "date": first["date"]}.items()}
    line.version += 1
    line.updated_by, line.validated_at = user, None if cancel else timezone.now()
    line.validation_origin = inventory.campaign if not cancel else None
    line.comment = link.comment
    line.source_signature = signature(line)
    line.save()
    line.group.version += 1
    line.group.save(update_fields=["version"])
    ReviewEvent.objects.create(line=line, actor=user, campaign=inventory.campaign,
        snapshot={"before": before, "state": line.state, "values": line.values, "version": line.version,
                  "validation_source": "MANUAL", "matching_decision": "INVENTORY_MANUAL_CANCEL" if cancel else "INVENTORY_MANUAL",
                  "comment": line.comment, "source": source_snapshot(line), "inventory_link": link.pk})
    save_decision_snapshot(line)


def _assert_capacity(campaign, keys):
    """Refuse une confirmation dont une cible courante est ambiguë ou surconsommée.

    `keys` sont uniquement les cibles nouvellement confirmées, pas les anciennes
    pièces libérées. Les montants sont Decimal EUR et la tolérance celle de la
    campagne. ValidationError annule l'action parente et son recalcul/audit ;
    aucun état d'équilibre trompeur ne peut ainsi être publié par un bouton ancien.
    """
    tolerance = money(campaign.metadata.get("tolerance", "0.01"))
    for control in campaign.global_controls.filter(key__in=keys):
        data = control.current_data or control.data
        a, s, sent = money(data["accounted_total"]), money(data["sage_total"]), money(data["confirmed_sent_total"])
        if (data["state"] in ("INDETERMINE", "EXCLU") or a is None or s is None or sent is None
                or abs(a + sent) > abs(s) + tolerance):
            raise ValidationError("Affectation impossible : preuve ambiguë ou capacité de la pièce dépassée. Actualisez et vérifiez les montants.")


@transaction.atomic
def confirm_inventory_link(pk: int, user, *, entry_ids, comment: str, expected_version: int,
                           replace_existing: bool = False, request_id=None):
    """Confirme des écritures entières de l'inventaire, indépendamment du moteur.

    Verrouille la campagne, vérifie droits/versions, unicité, montants EUR et
    capacité sur toutes les pièces. Aucun partage partiel n'est inféré. Remplacer
    une décision antérieure exige replace_existing explicite et un commentaire.
    Retourne l'inventaire actualisé ; tout refus annule allocations, décision,
    recalcul et audit. Une répétition du même UUID est idempotente.
    """
    inventory = _locked_inventory(pk, user)
    ids = sorted(str(v) for v in entry_ids)
    payload = {"kind": "LINK", "ids": ids, "comment": comment.strip(), "replace": replace_existing, "version": expected_version}
    key, fingerprint, done = _request(inventory, request_id, payload, expected_version)
    if done:
        return inventory
    if not comment.strip():
        raise ValidationError("Expliquez votre rapprochement manuel dans le commentaire.")
    adjustment = getattr(inventory, "adjustment", None)
    if adjustment and adjustment.active and adjustment.reason == AtlasAdjustment.Reason.DUPLICATE:
        raise ValidationError("Une ligne exclue comme doublon ne peut pas consommer une écriture Sage.")
    summary = selection_summary(inventory, user, ids)
    retained, total = summary["retained"], summary["sage_total"]
    tolerance = money(inventory.campaign.metadata.get("tolerance", "0.01"))
    if retained is None or abs(retained - total) > tolerance or retained * total < 0:
        raise ValidationError("La sélection doit expliquer le montant retenu. Une affectation partielle non démontrée reste à revoir.")
    line, previous = line_for(inventory), getattr(inventory, "inventory_match", None)
    if (previous and previous.active or line and line.version and line.state in ("VALIDATED", "REJECTED")) and not replace_existing:
        raise ValidationError("Confirmez explicitement le remplacement de la décision ou de l'affectation existante.")
    entries, keys = summary["entries"], affected_keys(inventory)
    if ManualAllocation.objects.filter(entry_id__in=[e.pk for e in entries], active=True).exclude(link__inventory=inventory).exists():
        raise ValidationError("Une écriture sélectionnée est déjà affectée. Actualisez la sélection.")
    references = {e.entry_ref for e in entries}
    for contribution in ControlContribution.objects.filter(control__campaign=inventory.campaign,
            control__key__in={e.control_key for e in entries}).select_related("line__transaction__project", "line__group", "line__campaign"):
        if line and contribution.line_id == line.pk:
            continue
        if references.intersection(contribution.entries) and contribution_is_current(contribution):
            raise ValidationError("Cette écriture Sage est déjà consommée par une validation actuelle.")
    before = _snapshot(inventory)
    link = previous or ManualReconciliation(inventory=inventory)
    if previous:
        link.version += 1
        link.allocations.filter(active=True).update(active=False)
    link.active, link.amount, link.adjustment_version = True, retained, adjustment_version(inventory)
    link.actor, link.comment = user, comment.strip()
    link.save()
    try:
        ManualAllocation.objects.bulk_create([ManualAllocation(link=link, entry=e, amount=money(e.data["entry"]["amount"])) for e in entries])
    except IntegrityError as exc:
        raise ValidationError("Cette écriture vient d'être affectée. Actualisez la page.") from exc
    _mirror_link(inventory, link, user)
    keys.update(e.control_key for e in entries)
    result = _finish(inventory, user, key, fingerprint, "LINK", before, keys)
    _assert_capacity(inventory.campaign, {e.control_key for e in entries})
    return result


@transaction.atomic
def cancel_inventory_link(pk: int, user, *, expected_version: int, comment: str = "", request_id=None):
    """Annule logiquement un lien manuel et libère ses écritures dans la même transaction.

    Retourne la ligne actualisée ; conserve allocations passées, auteur et
    événement. Droits/version/UUID sont contrôlés avant toute mutation et seules
    les anciennes pièces concernées sont recalculées, jamais la campagne entière.
    """
    inventory = _locked_inventory(pk, user)
    payload = {"kind": "UNLINK", "comment": comment.strip(), "version": expected_version}
    key, fingerprint, done = _request(inventory, request_id, payload, expected_version)
    if done:
        return inventory
    link = getattr(inventory, "inventory_match", None)
    if not link or not link.active:
        return inventory
    before, keys = _snapshot(inventory), affected_keys(inventory)
    link.active, link.actor, link.comment = False, user, comment.strip() or "Annulation du rapprochement manuel"
    link.version += 1
    link.save()
    link.allocations.filter(active=True).update(active=False)
    _mirror_link(inventory, link, user, cancel=True)
    return _finish(inventory, user, key, fingerprint, "UNLINK", before, keys)


def prepare_review_change(line, resolved, state, *, automatic=False, actor=None):
    """Capture les anciennes cibles d'une décision existante et vérifie la correction.

    Appel sous le verrou Campaign de decide, après contrôle des versions/droits.
    Retourne (inventaire, avant, clés) ou None pendant l'import/sans inventaire
    Lot 1. Une correction ne vaut pas validation ; un lien manuel actif doit être
    modifié explicitement dans son parcours dédié. Refus/réouverture annulent
    logiquement son lien, attribué à `actor`, avec le ReviewEvent de l'action.
    Aucun recalcul ici.
    """
    if IMPORTING.get() or not line.campaign_id or CAPABILITY not in line.campaign.metadata.get("capabilities", []):
        return None
    inventory = CampaignInventory.objects.filter(campaign=line.campaign, business_key=line.transaction.business_key,
                                                present=True).select_related("campaign", "adjustment", "inventory_match").first()
    if inventory is None:
        return None
    before, keys = _snapshot(inventory), affected_keys(inventory)
    correction = getattr(inventory, "adjustment", None)
    if correction and correction.active and state == "VALIDATED":
        if automatic or correction.reason == AtlasAdjustment.Reason.DUPLICATE:
            raise ValidationError("Cette correction exige une revue manuelle ; un doublon exclu ne peut pas être confirmé.")
        if money(resolved["amount"]) != retained_amount(inventory):
            raise ValidationError("Le montant validé doit correspondre au montant métier retenu.")
    if line.inventory_link_id and line.inventory_link.active:
        if state == "VALIDATED":
            raise ValidationError("Modifiez ce rapprochement via Rechercher une correspondance, ou annulez-le explicitement.")
        link = line.inventory_link
        link.active, link.version = False, link.version + 1
        link.actor = actor
        link.save(update_fields=["active", "version", "actor", "updated_at"])
        link.allocations.filter(active=True).update(active=False)
    line.inventory_link = None
    line.adjustment_version = adjustment_version(inventory)
    return inventory, before, keys


def after_review_change(context, line, user):
    """Recalcule après la décision effective et audite seulement les groupes impactés.

    `context` provient de prepare_review_change ; None suspend le hook pendant
    l'import initial. Retourne None et conserve la transaction de decide ; un
    échec de recalcul annule aussi décision/événement. Aucun recalcul sur lecture.
    """
    if context is None:
        return
    inventory, before, keys = context
    _finish(inventory, user, uuid4(), digest({"decision": line.pk, "version": line.version}),
            "DECISION", before, keys)
    if line.state == "VALIDATED":
        current_keys = set(ControlContribution.objects.filter(control__campaign=inventory.campaign, line=line).values_list("control__key", flat=True))
        _assert_capacity(inventory.campaign, current_keys)
