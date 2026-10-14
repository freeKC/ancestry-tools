"""Persistance de l'état du pipeline (candidates + éléments en cours) en JSON."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .models import Bounty, PipelineItem, Stage, now_iso, parse_ref


class StateStore:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.candidates: dict[str, Bounty] = {}
        self.items: dict[str, PipelineItem] = {}
        self.meta: dict[str, Any] = {}
        self.load()

    # ---------------------------------------------------------------- disque
    def load(self) -> None:
        if not self.path.is_file():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.meta = data.get("meta", {})
        self.candidates = {k: Bounty.from_dict(v) for k, v in data.get("candidates", {}).items()}
        self.items = {k: PipelineItem.from_dict(v) for k, v in data.get("items", {}).items()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.meta["saved_at"] = now_iso()
        payload = {
            "meta": self.meta,
            "candidates": {k: v.to_dict() for k, v in sorted(self.candidates.items())},
            "items": {k: v.to_dict() for k, v in sorted(self.items.items())},
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".state-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------ candidates
    def add_candidates(self, bounties: Iterable[Bounty]) -> tuple[int, int]:
        added = updated = 0
        for b in bounties:
            if b.key in self.candidates:
                current = self.candidates[b.key]
                for name in ("title", "amount_usd", "created_at", "language", "body", "platform"):
                    value = getattr(b, name)
                    if value and value != "inconnu":
                        setattr(current, name, value)
                current.labels = sorted(set(current.labels) | set(b.labels))
                current.prescore = b.prescore if b.prescore is not None else current.prescore
                current.prescore_notes = b.prescore_notes or current.prescore_notes
                updated += 1
            else:
                self.candidates[b.key] = b
                added += 1
        return added, updated

    def ranked_candidates(self) -> list[Bounty]:
        return sorted(self.candidates.values(), key=lambda b: (-(b.prescore or 0), b.key))

    # ----------------------------------------------------------------- items
    def resolve_key(self, ref: str) -> str:
        owner, repo, number = parse_ref(ref)
        return f"{owner}/{repo}#{number}"

    def get_item(self, ref: str) -> PipelineItem | None:
        return self.items.get(self.resolve_key(ref))

    def require_item(self, ref: str) -> PipelineItem:
        item = self.get_item(ref)
        if item is None:
            raise KeyError(f"Aucune prime {self.resolve_key(ref)} dans le pipeline : lance d'abord `analyze`/`pick`.")
        return item

    def ensure_item(self, ref: str) -> PipelineItem:
        key = self.resolve_key(ref)
        if key in self.items:
            return self.items[key]
        bounty = self.candidates.get(key) or Bounty.from_ref(ref)
        item = PipelineItem(bounty=bounty)
        item.log("ajoutée au pipeline", Stage.RECHERCHE)
        self.items[key] = item
        return item

    def active_items(self) -> list[PipelineItem]:
        return [i for i in self.items.values() if i.stage not in (Stage.TERMINE, Stage.ABANDONNE)]

    # ----------------------------------------------------------------- vues
    def table(self) -> str:
        if not self.items:
            return "(pipeline vide)"
        rows = ["| Prime | Montant | Étape | Verdict | PR | Intervention attendue |", "|---|---|---|---|---|---|"]
        for item in sorted(self.items.values(), key=lambda i: i.updated_at, reverse=True):
            b, a = item.bounty, item.analysis
            amount = f"{(a.amount_usd if a and a.amount_usd else b.amount_usd) or 0:.0f} $" \
                if (a and a.amount_usd) or b.amount_usd else "?"
            verdict = f"{a.verdict} ({a.score})" if a else "-"
            pr = item.pr_url or "-"
            if item.pr_state:
                pr += f" ({item.pr_state}{', payée' if item.paid else ''})"
            rows.append(f"| {b.key} | {amount} | {item.stage.value} | {verdict} | {pr} | {item.checkpoint or '-'} |")
        return "\n".join(rows)
