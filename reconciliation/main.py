"""Interface CLI de chargement et rapprochement pour UiPath."""

import argparse
import logging
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
    """Charge et rapproche ; retourne 0 en succès, 1 en erreur de traitement."""
    parser = argparse.ArgumentParser(description="Rapprocher les extractions Atlas et Sage")
    parser.add_argument("--atlas", required=True, help="Chemin du JDD .xlsx")
    parser.add_argument("--sage", required=True, help="Chemin du CSV Sage annuel")
    parser.add_argument("--output", help="Classeur .xlsx de résultats et tentatives (optionnel)")
    parser.add_argument("--trace", help="Journal JSONL ; par défaut <output>.tentatives.jsonl")
    parser.add_argument("--trace-mode", choices=("compact", "detailed"), default="compact")
    parser.add_argument("--review-output", help="Propositions JSONL pour l'application de validation")
    parser.add_argument("--campaign-name", help="Nom de la campagne de validation")
    parser.add_argument("--accounted-amount-field", choices=("total_sage_charges", "total_project_charges"),
                        default="total_sage_charges",
                        help="Montant individuel des Comptabilisé (défaut : total_sage_charges, confirmé métier)")
    parser.add_argument("--multiple-tolerance", default="0.01", help="Tolérance en euros du contrôle des multiples")
    parser.add_argument("--year", type=int, help="Année Atlas et année de la date comptable SAGE (2000–2200)")
    parser.add_argument("--campaign-scope", default="atlas-complet", help="Périmètre cumulatif stable de l'extraction")
    args = parser.parse_args(argv)
    from reconciliation_contract import money
    if money(args.multiple_tolerance) is None or money(args.multiple_tolerance) < 0:
        parser.error("--multiple-tolerance doit être un montant positif ou nul")
    if args.year is not None and not 2000 <= args.year <= 2200:
        parser.error("--year doit être compris entre 2000 et 2200")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    try:
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
            protected = [args.atlas, args.sage, args.output, trace_path]
            if any(Path(args.review_output).resolve() == Path(p).resolve() for p in protected if p):
                raise ExportError("Le fichier de validation doit être distinct des sources et autres sorties")
            try:
                logging.info("Ecriture des propositions pour validation")
                from reconciliation.multiples import build_controls
                controls = build_controls(frames['Atlas'], frames['Sage'], result,
                                          amount_field=args.accounted_amount_field,
                                          tolerance=args.multiple_tolerance)
                path = export_review_bundle(frames["Atlas"], frames["Sage"], result, args.review_output,
                                           campaign_name=args.campaign_name, scope=args.campaign_scope,
                                           year=args.year,
                                           controls=controls, amount_field=args.accounted_amount_field,
                                           tolerance=args.multiple_tolerance,
                                           source_paths={"Atlas": args.atlas, "SAGE": args.sage})
            except (ValueError, OSError) as exc:
                raise ExportError(str(exc)) from exc
            print(f"Propositions pour validation : {path}")
        if args.output:
            path = export_reconciliation(frames["Atlas"], result, args.output,
                                         source_paths={"Atlas": args.atlas, "Sage": args.sage})
            print(f"Classeur de rapprochement : {path}")
    except (LoaderError, TransformationError, ExportError, TraceError) as exc:
        logging.getLogger(__name__).error("Chargement interrompu : %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
