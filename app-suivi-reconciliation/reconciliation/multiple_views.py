"""Consultation des multiples et export d'audit, indépendants des corrections aval."""

import json
from heapq import merge

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from .campaign_views import campaigns_for, projects_for, reviews_for
from .models import MultipleControl, MultipleEvent, ReviewEvent
from .multiple_review import review_control


def controls_for(user):
    """Applique le portefeuille aussi aux contrôles sans proposition Envoyé SAGE."""
    rows = MultipleControl.objects.filter(campaign__published=True)
    if not user.is_global_admin:
        rows = rows.filter(project_code__in=projects_for(user).values("code"))
    return rows.select_related("campaign", "actor", "origin")


@login_required
@require_GET
def control_list(request, pk):
    """Liste paginée d'une campagne, filtrable par projet, stratégie et deux états."""
    campaign = get_object_or_404(campaigns_for(request.user), pk=pk)
    rows = controls_for(request.user).filter(campaign=campaign)
    filters = {
        key: request.GET.get(key, "") for key in ("project_code", "strategy", "status", "state")
    }
    for key, value in filters.items():
        if value:
            rows = rows.filter(**{key: value})
    page = Paginator(rows.order_by("project_code", "pk"), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "reconciliation/multiple_list.html",
        {
            "campaign": campaign,
            "page": page,
            "filters": filters,
            "projects": controls_for(request.user)
            .filter(campaign=campaign)
            .order_by("project_code")
            .values_list("project_code", flat=True)
            .distinct(),
            "page_range": page.paginator.get_elided_page_range(page.number),
        },
    )


@login_required
def control_detail(request, pk):
    """Présente les preuves sources et enregistre seulement un arbitrage motivé."""
    control = get_object_or_404(controls_for(request.user), pk=pk)
    error = ""
    if request.method == "POST":
        try:
            review_control(
                pk,
                request.user,
                state=request.POST.get("state"),
                comment=request.POST.get("comment", ""),
                version=int(request.POST.get("version", "-1")),
            )
        except (ValidationError, ValueError) as exc:
            error = (
                " ; ".join(exc.messages) if isinstance(exc, ValidationError) else "Version invalide"
            )
        else:
            messages.success(request, "Arbitrage enregistré et historisé.")
            return redirect("reconciliation:multiple-detail", pk=pk)
    return render(
        request,
        "reconciliation/multiple_detail.html",
        {
            "control": control,
            "error": error,
            "events": control.events.select_related("actor").order_by("-pk")[:50],
        },
    )


class AuditSheet:
    """Écrit progressivement, fractionne Excel et force les textes sans formules."""

    def __init__(self, book, name, headers):
        """Prépare une feuille avec ses colonnes ; les suivantes réutilisent les en-têtes."""
        self.book, self.name, self.headers = book, name, headers
        self.part, self.count = 0, 1_048_575

    def append(self, values):
        """Ajoute une ligne sans tronquer silencieusement une preuve trop longue."""
        if self.count == 1_048_575:
            self.part += 1
            self.sheet = self.book.create_sheet(
                self.name if self.part == 1 else f"{self.name}_{self.part}"
            )
            self.sheet.append(self.headers)
            self.count = 0
        cells = []
        for value in values:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and len(value) > 32767:
                raise ValidationError(
                    "Une preuve dépasse la capacité d’une cellule Excel ; réduisez le périmètre"
                )
            cell = WriteOnlyCell(self.sheet, value)
            if isinstance(value, str):
                cell.data_type = "s"
            cells.append(cell)
        self.sheet.append(cells)
        self.count += 1


@login_required
@require_GET
def audit_export(request, pk):
    """Exporte l'état photographié et le journal de la campagne sélectionnée uniquement."""
    campaign = get_object_or_404(campaigns_for(request.user), pk=pk)
    rows = reviews_for(request.user).filter(campaign=campaign)
    controls = controls_for(request.user).filter(campaign=campaign)
    project = request.GET.get("project", "").strip()
    if project:
        rows, controls = rows.filter(project__code=project), controls.filter(project_code=project)
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="audit-campagne-{pk}.xlsx"'
    book = Workbook(write_only=True)
    decisions = AuditSheet(
        book,
        "Décisions",
        [
            "Id Atlas",
            "Projet",
            "Exercice",
            "Groupe",
            "Statut moteur",
            "Règle moteur",
            "Décision",
            "Affectation",
            "Source",
            "Valeurs effectives",
            "Commentaire",
            "Auteur",
            "Date",
            "Origine",
            "Reprise",
            "Actuelle",
            "Motifs",
            "Diagnostic multiples",
        ],
    )
    assignments = AuditSheet(
        book,
        "Affectations SAGE",
        [
            "Id Atlas",
            "Projet",
            "Référence stable",
            "Pièce",
            "Date",
            "Montant individuel",
            "Écriture",
        ],
    )
    for row in rows.iterator(chunk_size=500):
        s, d = row.source, row.decision
        decisions.append(
            [
                s["source_id"],
                s["project_code"],
                s["fiscal_year"],
                row.group.key,
                row.group.data["match_status"],
                row.group.data["rule"],
                d["state"],
                "MANUAL_MATCH" if d.get("manual_assignment") else "",
                s,
                d["effective"],
                d["comment"],
                d.get("actor"),
                d.get("updated_at"),
                d.get("origin_name"),
                row.comparison,
                d["current"],
                row.reasons,
                d.get("multiple_diagnostic", {}),
            ]
        )
        for e in d.get("manual_assignment", []):
            assignments.append(
                [
                    s["source_id"],
                    s["project_code"],
                    e["ref"],
                    e["document"],
                    e["date"],
                    e["amount"],
                    e,
                ]
            )
    multiples = AuditSheet(
        book,
        "Multiples",
        [
            "Clé",
            "Projet",
            "Stratégie",
            "Statut source",
            "Total Atlas",
            "Total SAGE",
            "Écart",
            "Incertitudes",
            "Revue",
            "Commentaire",
            "Auteur",
            "Date",
            "Origine",
            "Signature",
        ],
    )
    proofs = AuditSheet(
        book, "Preuves multiples", ["Clé contrôle", "Source", "Identifiant", "Données"]
    )
    for c in controls.iterator(chunk_size=500):
        d = c.data
        multiples.append(
            [
                c.key,
                c.project_code,
                c.strategy,
                c.status,
                d["atlas_total"],
                d["sage_total"],
                d["gap"],
                d["reasons"],
                c.state,
                c.comment,
                str(c.actor or ""),
                c.reviewed_at.isoformat() if c.reviewed_at else "",
                str(c.origin or ""),
                d["signature"],
            ]
        )
        for a in d["atlas"]:
            proofs.append([c.key, "ATLAS", a["source_id"], a])
        for e in d["entries"]:
            proofs.append([c.key, "SAGE", e["ref"], e])
    journal = AuditSheet(book, "Journal", ["Type", "Objet", "Date UTC", "Auteur", "Événement"])
    line_events = (
        ReviewEvent.objects.filter(campaign=campaign, line_id__in=rows.values("line_id"))
        .select_related("actor")
        .order_by("created_at", "pk")
        .iterator(chunk_size=500)
    )
    control_events = (
        MultipleEvent.objects.filter(control__in=controls)
        .select_related("actor")
        .order_by("created_at", "pk")
        .iterator(chunk_size=500)
    )
    for event in merge(line_events, control_events, key=lambda e: (e.created_at, e.pk)):
        is_line = isinstance(event, ReviewEvent)
        journal.append(
            [
                "VALIDATION" if is_line else "MULTIPLE",
                event.line_id if is_line else event.control_id,
                event.created_at.isoformat(),
                str(event.actor or ""),
                event.snapshot,
            ]
        )
    if not book.worksheets:
        book.create_sheet("Aucune décision")
    book.save(response)
    book.close()
    return response
