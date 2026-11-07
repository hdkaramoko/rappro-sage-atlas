"""Présentation et filtres du parcours métier, sans calcul de rapprochement."""

from urllib.parse import urlsplit

from django.db.models import Q
from django.urls import Resolver404, resolve, reverse


def selections(query, name, allowed, default=()):
    """Lit les valeurs GET multiples autorisées ; une valeur vide signifie Toutes.

    Les anciennes valeurs scalaires restent acceptées. Valeurs inconnues ignorées,
    doublons retirés, défaut seulement si le paramètre est absent. Lecture pure.
    """
    values = query.getlist(name) if name in query else list(default)
    if "" in values:
        return []
    return list(dict.fromkeys(value for value in values if value in allowed))


def filter_menu(name, label, choices, selected):
    """Construit les cases et le résumé accessible d'un filtre serveur sans mutation."""
    return {"name": name, "label": label, "selected": selected,
            "summary": "Toutes" if not selected else f"{len(selected)} sélection(s)",
            "choices": [{"value": value, "label": title, "checked": value in selected} for value, title in choices]}


def no_match_query():
    """Identifie en SQL l'absence de proposition exploitable, indépendamment de sa règle.

    UNMATCHED inclut les anciennes règles pourtant renseignées. Les groupes ambigus
    restent distincts : ils ont des candidats à examiner et ne sont pas sans preuve.
    MATCH_CONFIRMED_ATLAS conserve sa preuve locale même sans candidats importés.
    """
    return Q(group__match_status="UNMATCHED") | (
        Q(group__match_status="MATCHED", group__evidence=[]) & ~Q(group__rule="MATCH_CONFIRMED_ATLAS"))


def safe_return(value, fallback=None):
    """Conserve uniquement un retour local vers les écrans autorisés du parcours.

    Refuse hôte, schéma, chemins inconnus et redirections externes. Préserve la
    query string complète, donc multisélections et pagination. Aucune écriture.
    """
    fallback = fallback or reverse("reconciliation:reviews")
    try:
        parsed = urlsplit(value)
    except ValueError:
        return fallback
    if "\\" in value or any(ord(char) < 32 for char in value):
        return fallback
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return fallback
    try:
        target = resolve(parsed.path)
    except Resolver404:
        return fallback
    return value if target.namespace == "reconciliation" and target.url_name in (
        "reviews", "review-detail", "global-control-detail") else fallback


def line_actions(line, inventory):
    """Dérive les actions visibles de la décision, de sa fraîcheur et des preuves.

    Ne décide ni ne valide. Les droits proviennent de la vue portefeuille ; les
    écritures sont à nouveau protégées par les services transactionnels au POST.
    Correction proposée sur montant absent/incohérent ou correction déjà active.
    """
    from .review import is_current
    confirmed = line.state == "VALIDATED" and is_current(line)
    writable = bool(line.campaign is None or line.campaign.is_current and line.campaign.published)
    usable = (line.group.match_status == "MATCHED" and
              (any(c.get("rows") for c in line.group.evidence) or line.group.rule == "MATCH_CONFIRMED_ATLAS"))
    manual = bool(inventory and not confirmed and (not usable or line.state == "REJECTED"))
    amount = line.transaction.total_project_charges
    anomaly = (amount is None or line.group.sage_total is not None and amount != line.group.sage_total
               or inventory and getattr(inventory, "adjustment", None) and inventory.adjustment.active)
    return {"confirmed": confirmed, "can_revise": writable and confirmed,
            "show_decision": writable and not confirmed,
            "show_search": writable and manual, "show_correction": writable and manual and bool(anomaly)}
