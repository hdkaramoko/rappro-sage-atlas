"""Journal optionnel des étapes réellement exécutées et des candidats examinés."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import pandas as pd


class TraceError(ValueError):
    """Échec d'écriture ou journal incomplet ; ne jamais perdre l'audit silencieusement."""


def json_value(value):
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def iter_attempts(result):
    """Relit progressivement le journal disque, ou l'ancien journal en mémoire."""
    path = result.attrs.get("matching_trace_path")
    if not path:
        yield from result.attrs.get("matching_attempts", [])
        return
    count, complete = 0, False
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                if complete:
                    raise TraceError("Données présentes après la fin du journal")
                row = json.loads(line)
                if "_trace_complete" in row:
                    complete = True
                    if row.get("trace_id") != result.attrs.get("trace_id"):
                        raise TraceError("Le journal a été remplacé par celui d'une autre exécution")
                    if row["_trace_complete"] != count or count != result.attrs["trace_row_count"]:
                        raise TraceError("Nombre de tentatives incohérent dans le journal")
                else:
                    if set(row) != set(TRACE_COLUMNS):
                        raise TraceError("Schéma de tentative invalide")
                    count += 1
                    yield row
        if not complete:
            raise TraceError("Journal interrompu : marqueur de fin absent")
    except (OSError, json.JSONDecodeError) as exc:
        raise TraceError(f"Lecture du journal impossible : {exc}") from exc

STAGES = ("PREUVE_ATLAS", "FILTRE_STRUCTURE", "FILTRE_MONTANT", "MATCH_EXACT",
          "MATCH_AMOUNT", "FUZZY", "MATCH_WITHOUT_LABEL", "MATCH_BAP", "MATCH_INDIVIDUAL")
TRACE_COLUMNS = (
    "atlas_group_id", "atlas_source_ids", "stage", "outcome", "reason",
    "candidates_before", "candidates_after", "sage_group_id", "project_code",
    "third_party_code", "matching_reference", "atlas_label", "sage_label",
    "atlas_amount", "sage_amount", "amount_difference", "atlas_row_count",
    "sage_row_count", "label_similarity", "sage_source_ids", "sage_documents", "sage_dates",
)


class Trace:
    """Une ligne de synthèse par filtre et une ligne par candidat évalué par règle."""

    def __init__(self, enabled, *, path=None, mode="compact", flush_every=1000):
        if mode not in ("compact", "detailed"):
            raise TraceError("Mode de journal attendu : compact ou detailed")
        self.enabled = enabled
        self.rows = []
        self.mode = mode
        self.path = Path(path).resolve() if enabled and path else None
        self.stream = None
        self.temporary = None
        self.count = 0
        self.trace_id = uuid4().hex
        self.flush_every = flush_every

    def __enter__(self):
        if self.path:
            if self.path.suffix.lower() != ".jsonl":
                raise TraceError("Le journal disque doit porter l'extension .jsonl")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.stream = NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                                dir=self.path.parent, suffix=".jsonl.part", delete=False)
                self.temporary = Path(self.stream.name)
            except OSError as exc:
                raise TraceError(f"Création du journal impossible : {exc}") from exc
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.stream:
            try:
                if exc_type is None:
                    self.stream.write(json.dumps({"_trace_complete": self.count, "trace_id": self.trace_id}) + "\n")
                self.stream.close()
                if exc_type is None:
                    os.replace(self.temporary, self.path)
            except OSError as error:
                raise TraceError(f"Finalisation du journal impossible : {error}") from error
            finally:
                if not self.stream.closed:
                    self.stream.close()
                if self.temporary.exists():
                    self.temporary.unlink()

    def emit(self, row):
        if self.stream:
            try:
                self.stream.write(json.dumps(json_value(row), ensure_ascii=False, allow_nan=False) + "\n")
                if (self.count + 1) % self.flush_every == 0:
                    self.stream.flush()
            except (OSError, ValueError) as exc:
                raise TraceError(f"Écriture du journal impossible : {exc}") from exc
        else:
            self.rows.append(row)
        self.count += 1

    def add(self, result, stage, outcome, reason, *, before=None, after=None,
            atlas=None, sage=None, score=None):
        if not self.enabled:
            return
        atlas, sage = atlas or {}, sage or {}
        amount = sage.get("amount")
        self.emit(dict(zip(TRACE_COLUMNS, (
            result.atlas_group_id, result.atlas_source_ids, stage, outcome, reason,
            before, after, sage.get("group_id"), atlas.get("project_code"),
            atlas.get("third_party_code"), atlas.get("matching_reference"), atlas.get("label"),
            sage.get("label"), result.atlas_amount, amount,
            result.atlas_amount - amount if result.atlas_amount is not None and amount is not None else None,
            result.atlas_row_count, sage.get("row_count"), score,
            sage.get("source_ids"), sage.get("documents"), sage.get("dates"),
        ))))

    def candidates(self, result, stage, atlas, candidates, chosen, scores=None):
        if not self.enabled:
            return
        selected = {g["group_id"] for g in chosen}
        if not candidates:
            self.add(result, stage, "REJETE", "Aucun candidat à examiner", before=0, after=0, atlas=atlas)
        rejected = len(candidates) - len(chosen)
        if self.mode == "compact" and stage != "FUZZY" and rejected:
            self.add(result, stage, "REJETE", f"{rejected} candidats ne satisfont pas la clé complète ou la cardinalité",
                     before=len(candidates), after=len(chosen), atlas=atlas)
        for sage in candidates:
            accepted = sage["group_id"] in selected
            if self.mode == "compact" and stage != "FUZZY" and not accepted:
                continue
            reasons = {
                "MATCH_EXACT": "Clé complète ou cardinalité différente",
                "MATCH_AMOUNT": "Clé complète différente",
                "FUZZY": "Libellé absent ou score inférieur au seuil de revue",
            }
            self.add(result, stage, "RETENU" if accepted else "REJETE",
                     "Critères satisfaits ; sous réserve des contrôles finaux" if accepted else reasons.get(stage, "Critères non satisfaits"),
                     before=len(candidates), after=len(chosen), atlas=atlas, sage=sage,
                     score=(scores or {}).get(sage["group_id"]))

    def skipped(self, result, executed, reason):
        if not self.enabled:
            return
        skipped = [stage for stage in STAGES if stage not in executed]
        if self.mode == "compact":
            if skipped:
                self.add(result, "ETAPES_NON_EXECUTEES", "NON_EXECUTE", f"{', '.join(skipped)} : {reason}")
        else:
            for stage in skipped:
                self.add(result, stage, "NON_EXECUTE", reason)
