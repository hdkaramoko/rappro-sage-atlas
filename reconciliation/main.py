"""Interface CLI de chargement et rapprochement pour UiPath."""

import argparse
import logging

from reconciliation.loaders.atlas import load_atlas
from reconciliation.loaders.common import LoaderError
from reconciliation.loaders.sage import load_sage
from reconciliation.transformations.atlas import transform_atlas
from reconciliation.transformations.sage import transform_sage
from reconciliation.transformations.common import TransformationError
from reconciliation.matching import match_reconciliations, summarize_matching


def main(argv: list[str] | None = None) -> int:
    """Charge et rapproche ; retourne 0 en succès, 1 en erreur de traitement."""
    parser = argparse.ArgumentParser(description="Rapprocher les extractions Atlas et Sage")
    parser.add_argument("--atlas", required=True, help="Chemin du JDD .xlsx")
    parser.add_argument("--sage", required=True, help="Chemin du CSV Sage annuel")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    try:
        frames = {}
        for name, loader, transform, path in (
            ("Atlas", load_atlas, transform_atlas, args.atlas),
            ("Sage", load_sage, transform_sage, args.sage),
        ):
            frame = loader(path)
            summary = frame.attrs["load_summary"]
            frame = transform(frame)
            print(f"{name} :")
            if summary["valid_sheets"] is not None:
                print(f"- {summary['valid_sheets']} feuilles valides chargées")
            print(f"- {summary['rows_read']} lignes lues")
            print(f"- {summary['duplicates_removed']} doublons supprimés")
            print(f"- {summary['rows_final']} lignes finales")
            transformed = frame.attrs["transformation_summary"]
            print(f"- {transformed['rows_transformed']} lignes transformées")
            print(f"- {transformed['missing_project_codes']} codes projet manquants")
            frames[name] = frame
        result = match_reconciliations(frames["Atlas"], frames["Sage"])
        print("Rapprochement :")
        for rule, count in summarize_matching(result).items():
            print(f"- {rule} : {count}")
    except (LoaderError, TransformationError) as exc:
        logging.getLogger(__name__).error("Chargement interrompu : %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
