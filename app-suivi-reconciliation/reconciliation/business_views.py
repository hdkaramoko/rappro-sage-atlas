"""Détail métier de campagne : correction, recherche et confirmation explicites."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from reconciliation_contract import money
from reconciliation_contract.sage_inventory import CAPABILITY

from .business import (affected_keys, cancel_inventory_link, confirm_inventory_link,
                       contribution_is_current, correct_inventory, line_for, retained_amount, search_sage,
                       selection_summary, source_amount)
from .business_forms import AdjustmentForm, BusinessActionForm, CancelLinkForm, SageSearchForm
from .journey import safe_return
from .campaign_views import inventory_for
from .models import CampaignInventory, ControlContribution, ManualAllocation


@login_required
@require_http_methods(["GET", "POST"])
def inventory_detail(request, pk):
    """Présente une ligne Atlas exacte et les deux actions Lot 2 autorisées.

    `pk` identifie CampaignInventory, filtré par publication et portefeuille.
    GET/recherche/prévisualisation sont sans effet métier. POST délègue aux
    services atomiques (versions, UUID, corrections, capacité et audit).
    Retourne HTML ou redirection après succès ; les erreurs métier sont affichées
    dans le formulaire, les accès hors périmètre répondent 404.
    """
    inventory = get_object_or_404(inventory_for(request.user).select_related(
        "campaign", "adjustment", "inventory_match__actor", "adjustment__actor"), pk=pk)
    initial = {"version": inventory.business_version}
    adjustment = getattr(inventory, "adjustment", None)
    pending = inventory.business_events.filter(kind="CARRY_PENDING").first() if inventory.business_version == 0 else None
    correction_initial = {**initial, "reason": adjustment.reason if adjustment and adjustment.active else "AMOUNT",
                          "amount": adjustment.amount if adjustment and adjustment.active else source_amount(inventory)}
    if pending and pending.after.get("adjustment"):
        correction_initial.update(pending.after["adjustment"])
    action = request.POST.get("action", "") if request.method == "POST" else ""
    correction = AdjustmentForm(request.POST if action == "correct" else None, initial=correction_initial, auto_id="correction_%s")
    operation = BusinessActionForm(request.POST if action and action != "correct" else None, initial=initial, auto_id="operation_%s")
    cancellation = CancelLinkForm(request.POST if action == "cancel_link" else None, initial=initial, auto_id="cancel_%s")
    preview = None
    if request.method == "POST":
        form = correction if action == "correct" else cancellation if action == "cancel_link" else operation
        if form.is_valid():
            try:
                values = form.cleaned_data
                options = {"expected_version": values["version"], "request_id": values["request_id"], "comment": values["comment"]}
                if action == "correct":
                    correct_inventory(pk, request.user, reason=values["reason"], amount=values["amount"], **options)
                elif action == "cancel_correction":
                    correct_inventory(pk, request.user, cancel=True, **options)
                elif action == "preview":
                    if values["version"] != inventory.business_version:
                        raise ValidationError("Cette ligne a changé. Actualisez avant de confirmer.")
                    preview = selection_summary(inventory, request.user, request.POST.getlist("entries"))
                elif action == "confirm":
                    confirm_inventory_link(pk, request.user, entry_ids=request.POST.getlist("entries"),
                                           replace_existing=values["replace_existing"], **options)
                elif action == "cancel_link":
                    cancel_inventory_link(pk, request.user, **options)
                else:
                    raise ValidationError("Action inconnue.")
            except ValidationError as exc:
                form.add_error(None, exc)
                if action == "confirm":
                    try:
                        preview = selection_summary(inventory, request.user, request.POST.getlist("entries"))
                    except ValidationError:
                        pass
            else:
                if action != "preview":
                    messages.success(request, "Action enregistrée. Les contrôles concernés ont été actualisés.")
                    return redirect(request.get_full_path())
    search = SageSearchForm(request.GET, auto_id="search_%s")
    page, search_error = None, ""
    if inventory.campaign.is_current and search.is_valid():
        try:
            page = Paginator(search_sage(inventory, request.user, search.cleaned_data), 25).get_page(request.GET.get("page"))
        except ValidationError as exc:
            search_error = " ; ".join(exc.messages)
    link = getattr(inventory, "inventory_match", None)
    keys = affected_keys(inventory)
    controls = list(inventory.campaign.global_controls.filter(key__in=keys).order_by("key"))
    for control in controls:
        control.result = control.current_data or control.data
    if page:
        entries = list(page.object_list)
        entry_keys = {e.control_key for e in entries}
        capacities = {c.key: c.current_data or c.data for c in inventory.campaign.global_controls.filter(key__in=entry_keys)}
        reserved = set(ManualAllocation.objects.filter(active=True, entry_id__in=[e.pk for e in entries]).exclude(
            link__inventory=inventory).values_list("entry_id", flat=True))
        legacy_refs = set()
        contributions = list(ControlContribution.objects.filter(control__campaign=inventory.campaign, control__key__in=entry_keys).select_related(
                "control", "line__group", "line__transaction__project", "line__campaign"))
        bases = {row.business_key: row for row in CampaignInventory.objects.filter(campaign=inventory.campaign,
                 business_key__in={c.line.transaction.business_key for c in contributions}).select_related("adjustment")}
        for contribution in contributions:
            if (contribution.line.transaction.business_key != inventory.business_key
                    and contribution.line.transaction.business_key in bases
                    and contribution_is_current(contribution, bases[contribution.line.transaction.business_key])):
                legacy_refs.update(contribution.entries)
        for entry in entries:
            data = capacities.get(entry.control_key)
            entry.occupied = entry.pk in reserved or entry.entry_ref in legacy_refs
            entry.available = (money(data["sage_total"]) - money(data["accounted_total"]) - money(data["confirmed_sent_total"])) if data and data["state"] not in ("INDETERMINE", "EXCLU") and all(money(data[k]) is not None for k in ("sage_total", "accounted_total", "confirmed_sent_total")) else None
        page.object_list = entries
    line = line_for(inventory)
    from .review import effective, is_current
    confirmed = bool(line and line.state == "VALIDATED" and is_current(line) or
                     not line and link and link.active and link.adjustment_version == (adjustment.version if adjustment else 0))
    original, retained = source_amount(inventory), retained_amount(inventory)
    return render(request, "reconciliation/inventory_detail.html", {
        "inventory": inventory, "source_amount": source_amount(inventory), "retained": retained_amount(inventory),
        "correction_gap": retained - original if retained is not None and original is not None else None,
        "correction": correction, "operation": operation, "search": search, "page": page,
        "preview": preview, "search_error": search_error, "adjustment": adjustment, "link": link,
        "cancellation": cancellation, "confirmed": confirmed,
        "previous_values": effective(line) if line and line.state == "VALIDATED" else None,
        "return_url": safe_return(request.GET.get("return", ""),
                                  reverse("reconciliation:campaign", args=[inventory.campaign_id]) + "?tab=inventory"),
        "revision_open": not confirmed or bool(action) or request.GET.get("revise") == "1",
        "carry_pending": pending, "carry_event": inventory.business_events.filter(kind="CARRY").first(),
        "allocations": link.allocations.filter(active=True).select_related("entry") if link else [],
        "requires_replace": bool(link and link.active or line and line.version and line.state in ("VALIDATED", "REJECTED")),
        "controls": controls, "controls_available": CAPABILITY in inventory.campaign.metadata.get("capabilities", []),
        "events": Paginator(inventory.business_events.select_related("actor").order_by("-pk"), 25).get_page(request.GET.get("history_page")),
        "readonly": not inventory.campaign.is_current or not inventory.present,
    })
