"""Suivi après soumission : état de la PR et paiement de la prime."""
from __future__ import annotations

import re
from typing import Any

from .github import GitHubClient, GitHubError
from .models import PipelineItem, Stage

PAID_RE = re.compile(r"(rewarded|paid out|has been awarded|payment (?:sent|completed)|💰)", re.I)


def check_item(client: GitHubClient, item: PipelineItem, log=print) -> dict[str, Any]:
    b = item.bounty
    report: dict[str, Any] = {"key": b.key}
    if item.pr_number:
        try:
            pull = client.pull(b.owner, b.repo, item.pr_number)
            if pull.get("merged_at"):
                item.pr_state = "merged"
            else:
                item.pr_state = pull.get("state", item.pr_state)
            report["pr_state"] = item.pr_state
            report["pr_mergeable"] = pull.get("mergeable")
        except GitHubError as exc:
            report["pr_error"] = str(exc)
    try:
        issue = client.issue(b.owner, b.repo, b.number)
        labels = [l.get("name", "") for l in issue.get("labels", [])]
        report["issue_state"] = issue.get("state")
        b.state = issue.get("state", b.state)
        paid = any("rewarded" in label.lower() or "💰" in label for label in labels)
        if not paid:
            for c in client.issue_comments(b.owner, b.repo, b.number):
                user = c.get("user") or {}
                if (user.get("type") == "Bot" or user.get("login", "").endswith("[bot]")) \
                        and PAID_RE.search(c.get("body") or ""):
                    paid = True
                    item.paid_note = (c.get("body") or "")[:200]
                    break
        if paid and not item.paid:
            item.paid = True
            item.log("prime marquée payée (label ou commentaire de bot)", Stage.TERMINE)
        report["paid"] = item.paid
    except GitHubError as exc:
        report["issue_error"] = str(exc)
    if item.pr_state == "merged" and item.stage in (Stage.LIVRAISON, Stage.PAIEMENT) and not item.paid:
        item.log("PR fusionnée, en attente du paiement", Stage.PAIEMENT)
    elif item.pr_state == "closed" and item.stage == Stage.PAIEMENT:
        item.log("PR fermée sans fusion : vérifier les commentaires des mainteneurs")
    return report
