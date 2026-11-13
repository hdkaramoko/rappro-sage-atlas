"""Interface CLI de chargement et rapprochement pour UiPath."""

import argparse
import logging
import os
from tempfile import TemporaryDirectory
from contextlib import ExitStack
from pathlib import Path

from reconciliation.loaders.atlas import load_atlas
from reconciliation.loaders.common import LoaderError
from reconciliation.loaders.sage import load_sage
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.transformations.common import TransformationError
from reconciliation.matching import match_reconciliations, summarize_matching
from reconciliation.exporters.excel import export_reconciliation, ExportError
from reconciliation.matching.trace import TraceError
from reconciliation.exporters.review import export_review_bundle


def main(argv: list[str] | None = None) -> int:
    """Exécute la CLI sur `argv` (liste de chaînes ou arguments du processus).

    Charge les extractions, rapproche sans modifier la cascade et publie les
    sorties demandées. Le JSONL CLI inclut l'inventaire Sage v3 déclaré et les
    exclusions figées de config.py. Retourne 0 en succès, 1 si traitement en
    échec ; argparse lève SystemExit pour options invalides. Lit les sources et
    écrit les exports/trace, sans accès à la base Django.
    Les deux référentiels optionnels sont indissociables et exigent review-output.
    L'enrichissement est validé avant matching ; les inventaires sont préparés
    avec le JSONL puis publiés, JSONL en dernier comme marqueur de réussite.
    """
    parser = argparse.ArgumentParser(description="Rapprocher les extractions Atlas et Sage")
    parser.add_argument("--atlas", required=True, help="Chemin du JDD .xlsx")
    parser.add_argument("--sage", required=True, help="Chemin du CSV Sage annuel")
    parser.add_argument("--output", help="Classeur .xlsx de résultats et tentatives (optionnel)")
    parser.add_argument("--trace", help="Journal JSONL ; par défaut <output>.tentatives.jsonl")
    parser.add_argument("--trace-mode", choices=("compact", "detailed"), default="compact")
    parser.add_argument("--review-output", help="Propositions JSONL pour l'application de validation")
    parser.add_argument("--legacy-review-output", action="store_true",
                        help="Produit le contrat v3 historique sans inventaire Sage (compatibilité)")
    parser.add_argument("--campaign-name", help="Nom de la campagne de validation")
    parser.add_argument("--atlas-projects", help="Référentiel projets Atlas .xlsx (Sheet1)")
    parser.add_argument("--department-mapping", help="Transcodification des départements .xlsx (Feuil1)")
    parser.add_argument("--accounted-amount-field", choices=("total_sage_charges", "total_project_charges"),
                        default="total_sage_charges",
                        help="Montant individuel des Comptabilisé (défaut : total_sage_charges, confirmé métier)")
    parser.add_argument("--multiple-tolerance", default="0.01", help="Tolérance en euros du contrôle des multiples")
    parser.add_argument("--year", type=int, help="Année Atlas et année de la date comptable SAGE (2000–2200)")
    parser.add_argument("--campaign-scope", default="atlas-complet", help="Périmètre cumulatif stable de l'extraction")
    args = parser.parse_args(argv)
    if bool(args.atlas_projects) != bool(args.department_mapping):
        parser.error("--atlas-projects et --department-mapping doivent être fournis ensemble")
    if args.atlas_projects and (not args.review_output or args.legacy_review_output):
        parser.error("L'enrichissement départemental exige --review-output avec inventaire Sage complet")
    from reconciliation_contract import money
    if money(args.multiple_tolerance) is None or money(args.multiple_tolerance) < 0:
        parser.error("--multiple-tolerance doit être un montant positif ou nul")
    if args.year is not None and not 2000 <= args.year <= 2200:
        parser.error("--year doit être compris entre 2000 et 2200")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    try:
        with ExitStack() as stack:
            return run(args, stack)
    except (LoaderError, TransformationError, ExportError, TraceError, OSError) as exc:
        logging.getLogger(__name__).error("Chargement interrompu : %s", exc)
        return 1


def run(args, stack):
    """Exécute les arguments CLI validés et libère les temporaires via stack.

    Retourne 0 après publication ; propage les erreurs au gestionnaire CLI.
    Les départements restent un contexte séparé du matching. Les sources Excel
    ne sont jamais écrasées ; chaque remplacement de sortie est atomique, le
    JSONL étant publié en dernier. Aucun accès à la base applicative.
    """
    validate_output_paths(args)
    frames = {}
    for name, loader, transform, path in (
        ("Atlas", load_atlas, transform_atlas, args.atlas),
        ("Sage", load_sage, transform_sage, args.sage),
    ):
        logging.info("Chargement de l'extraction %s", name)
        frame = loader(path, year=args.year) if args.year is not None else loader(path)
        summary = frame.attrs["load_summary"]
        logging.info("Normalisation de l'extraction %s", name)
        frame = transform(frame)
        print(f"{name} :")
        if summary["valid_sheets"] is not None:
            print(f"- {summary['valid_sheets']} feuilles valides chargées")
        print(f"- {summary['rows_read']} lignes lues")
        print(f"- {summary['duplicates_removed']} doublons supprimés")
        if args.year is not None:
            print(f"- {summary['rows_excluded_by_year']} lignes exclues par le filtre annuel {args.year}")
        print(f"- {summary['rows_final']} lignes finales")
        transformed = frame.attrs["transformation_summary"]
        print(f"- {transformed['rows_transformed']} lignes transformées")
        print(f"- {transformed['missing_project_codes']} codes projet manquants")
        frames[name] = frame
    departments, department_summary, staging = None, None, None
    if args.atlas_projects:
        from reconciliation.departments import project_context
        departments, department_summary = project_context(frames["Atlas"], frames["Sage"], args.atlas_projects, args.department_mapping)
        logging.info("Bilan projets/départements : %s", department_summary)
        parent = Path(args.review_output).resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(stack.enter_context(TemporaryDirectory(dir=parent, prefix=".departments-")))
    trace_path = args.trace or (str(Path(args.output).with_suffix(".tentatives.jsonl")) if args.output else None)
    if trace_path and any(Path(trace_path).resolve() == Path(p).resolve() for p in (args.atlas, args.sage, args.output) if p):
        raise TraceError("Le journal ne doit pas remplacer une source ou le classeur de sortie")
    logging.info("Recherche des correspondances Atlas / SAGE")
    result = match_reconciliations(frames["Atlas"], frames["Sage"], trace_path=trace_path, trace_mode=args.trace_mode)
    if args.year is not None:
        result.attrs["population_summary"]["fiscal_year"] = args.year
    print("Rapprochement :")
    for rule, count in summarize_matching(result).items():
        print(f"- {rule} : {count}")
    if args.review_output:
        protected = [args.atlas, args.sage, args.output, trace_path, args.atlas_projects, args.department_mapping]
        if any(Path(args.review_output).resolve() == Path(p).resolve() for p in protected if p):
            raise ExportError("Le fichier de validation doit être distinct des sources et autres sorties")
        try:
            logging.info("Ecriture des propositions pour validation")
            from reconciliation.multiples import build_controls
            from reconciliation.config import SAGE_EXCLUDED_PREFIXES
            controls = build_controls(frames['Atlas'], frames['Sage'], result,
                                      amount_field=args.accounted_amount_field,
                                      tolerance=args.multiple_tolerance,
                                      excluded_prefixes=None if args.legacy_review_output else SAGE_EXCLUDED_PREFIXES)
            path = export_review_bundle(frames["Atlas"], frames["Sage"], result,
                                       staging / Path(args.review_output).name if staging else args.review_output,
                                       campaign_name=args.campaign_name, scope=args.campaign_scope,
                                       year=args.year,
                                       controls=controls, amount_field=args.accounted_amount_field,
                                       include_sage_inventory=not args.legacy_review_output,
                                       tolerance=args.multiple_tolerance,
                                       project_departments=departments, department_summary=department_summary,
                                       source_paths={"Atlas": args.atlas, "SAGE": args.sage,
                                           **({"Projets Atlas": args.atlas_projects, "Transcodification": args.department_mapping}
                                              if args.atlas_projects else {})})
        except (ValueError, OSError) as exc:
            raise ExportError(str(exc)) from exc
        if not staging:
            print(f"Propositions pour validation : {path}")
    if args.output:
        path = export_reconciliation(frames["Atlas"], result, staging / Path(args.output).name if staging else args.output,
                                     source_paths={"Atlas": args.atlas, "Sage": args.sage})
        if not staging:
            print(f"Classeur de rapprochement : {path}")
    if staging:
        from reconciliation.departments import project_exports
        inventories = project_exports(frames["Atlas"], frames["Sage"], departments, staging, Path(args.review_output).stem)
        sources = {Path(p).resolve() for p in (args.atlas, args.sage, args.atlas_projects, args.department_mapping)}
        destinations = [Path(args.review_output).resolve().parent / p.name for p in inventories]
        if any(p.resolve() in sources for p in destinations):
            raise ExportError("Un inventaire projets ne doit pas remplacer une source")
        for source, destination in zip(inventories, destinations):
            os.replace(source, destination)
            print(f"Inventaire projets : {destination}")
        if args.output:
            Path(args.output).resolve().parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / Path(args.output).name, args.output)
            print(f"Classeur de rapprochement : {args.output}")
        os.replace(staging / Path(args.review_output).name, args.review_output)
        print(f"Propositions pour validation : {args.review_output}")
    return 0


def validate_output_paths(args):
    """Refuse toute collision entre sources et sorties avant lecture/écriture.

    Inclut les référentiels, le journal implicite et les deux inventaires
    organisationnels. Lève ExportError ; ne crée aucun fichier ou dossier.
    """
    sources = {Path(p).resolve() for p in (args.atlas, args.sage, args.atlas_projects, args.department_mapping) if p}
    trace = args.trace or (str(Path(args.output).with_suffix(".tentatives.jsonl")) if args.output else None)
    outputs = [Path(p).resolve() for p in (args.output, args.review_output, trace) if p]
    if args.atlas_projects:
        target = Path(args.review_output).resolve()
        outputs += [target.parent / f"{prefix}_{target.stem}.xlsx" for prefix in ("projets_jdd_atlas", "projets_sage_absents_jdd")]
        if args.output and Path(args.output).name in {p.name for p in outputs if p != Path(args.output).resolve()}:
            raise ExportError("Les sorties enrichies doivent avoir des noms de fichiers distincts")
    if len(set(outputs)) != len(outputs) or any(path in sources for path in outputs):
        raise ExportError("Les sorties doivent être distinctes entre elles et des sources/référentiels")


if __name__ == "__main__":
    raise SystemExit(main())
