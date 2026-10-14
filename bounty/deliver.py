"""Livraison : titre et corps de PR, patch, checklist de validation pour l'utilisateur."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import PipelineItem, VerifyResult
from .workspace import git

FEATURE_WORDS = ("feature", "enhancement", "feat", "add ", "support", "implement")


def claim_line(item: PipelineItem, cfg: dict[str, Any]) -> str | None:
    template = cfg["livraison"].get("claim", {}).get(item.bounty.platform)
    return template.format(n=item.bounty.number) if template else None


def pr_title(item: PipelineItem, override: str | None = None) -> str:
    if override:
        return override[:72]
    b = item.bounty
    haystack = f"{b.title} {' '.join(b.labels)}".lower()
    prefix = "feat" if any(w in haystack for w in FEATURE_WORDS) and "bug" not in haystack else "fix"
    title = b.title.strip().rstrip(".")
    title = title[0].lower() + title[1:] if title else f"issue #{b.number}"
    return f"{prefix}: {title}"[:72]


def _results_table(results: list[VerifyResult]) -> list[str]:
    if not results:
        return ["_No automated checks recorded._"]
    rows = ["| Check | Result | Duration |", "|---|---|---|"]
    for r in results:
        rows.append(f"| `{r.command}` | {'✅ pass' if r.ok else f'❌ exit {r.returncode}'} | {r.duration_s}s |")
    return rows


def pr_body(item: PipelineItem, cfg: dict[str, Any], summary: str, approach: str,
            testing_notes: str, diff: dict[str, Any] | None = None) -> str:
    b = item.bounty
    lines = ["## Summary", "", summary.strip() or f"Resolves #{b.number}.", "",
             "## Approach", "", approach.strip() or "_(describe the change)_", ""]
    if diff and diff.get("files"):
        lines += ["## Files changed", ""] + [f"- `{f}`" for f in diff["files"]] + [""]
    lines += ["## Testing", "", testing_notes.strip() or "_(how this was verified)_", ""]
    lines += _results_table(item.verify_results) + [""]
    lines += [f"Fixes #{b.number}", ""]
    claim = claim_line(item, cfg)
    if claim:
        lines += [claim, ""]
    signature = cfg["livraison"].get("signature")
    if signature:
        lines += [signature, ""]
    return "\n".join(lines)


def user_checklist(item: PipelineItem, cfg: dict[str, Any], diff: dict[str, Any] | None,
                   violations: list[Any] | None = None) -> str:
    b, a = item.bounty, item.analysis
    lines = [
        f"# Validation de la soumission : {b.key}",
        "",
        "À vérifier avant `python -m bounty submit` :",
        "",
        f"- [ ] L'issue {b.url} est toujours ouverte et la prime toujours affichée.",
        "- [ ] Aucune PR concurrente n'a été fusionnée entre-temps.",
        "- [ ] Le diff ne touche que le périmètre de l'issue (voir ci-dessous).",
        "- [ ] Les tests passent (tableau des vérifications dans PR.md).",
        "- [ ] Les règles de contribution du dépôt (CONTRIBUTING) sont respectées.",
    ]
    if violations:
        lines += ["", "## Règles de publication : écarts à corriger avant soumission", ""]
        lines += [f"- [ ] {v}" for v in violations[:50]]
        lines.append("")
    elif violations is not None:
        lines.append("- [x] Règles de publication : aucun écart (tirets longs, trailers, mots proscrits).")
    if a:
        for c in a.conditions:
            lines.append(f"- [ ] Condition : {c}")
    if b.platform == "algora":
        lines.append("- [ ] Compte Algora lié au compte GitHub et moyen de paiement (Stripe) configuré.")
        lines.append(f"- [ ] Le corps de la PR contient `/claim #{b.number}`.")
    if diff:
        lines += ["", "## Diff", "", "```", diff.get("stat") or "(vide)", "```", ""]
        if diff.get("commits"):
            lines += ["Commits :"] + [f"- {c}" for c in diff["commits"]] + [""]
        if diff.get("uncommitted"):
            lines.append("⚠️ Des modifications ne sont pas commitées dans l'espace de travail.")
    lines += ["", "Intervention attendue : **Valider la soumission** (`python -m bounty submit <clé>`)."]
    return "\n".join(lines)


def export_patch(path: Path, base: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    patch = out_dir / "changes.patch"
    merge_base = git(["merge-base", f"origin/{base}", "HEAD"], path, check=False) or f"origin/{base}"
    content = git(["format-patch", "--stdout", f"{merge_base}..HEAD"], path, check=False)
    if not content.strip():
        content = git(["diff", merge_base], path, check=False)
    patch.write_text(content + ("\n" if content and not content.endswith("\n") else ""), encoding="utf-8")
    return patch
