"""Analyse d'une prime : conditions, concurrence, santé du dépôt, verdict."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .github import GitHubClient, GitHubError
from .models import CHECKPOINTS, PIPELINE_WORK, Analysis, Bounty, PipelineItem, parse_iso
from .sources import parse_amount

CLAIM_RE = re.compile(r"^\s*/(attempt|claim|opire\s+(?:try|claim)|bounty\s+claim)\b", re.I | re.M)
PR_MENTION_RE = re.compile(r"\b(?:PR|pull request|pull)\s*#?(\d{1,6})\b", re.I)
BOT_BOUNTY_RE = re.compile(r"(💎|bounty)", re.I)
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*(.+)$", re.M)
CONDITION_HINTS = (
    "must", "should", "required", "requirement", "acceptance", "criteria", "deadline",
    "expected", "doit", "obligatoire", "critère", "délai",
)
TEST_MARKERS = {
    "tests", "test", "spec", "specs", "__tests__", "pytest.ini", "tox.ini", "conftest.py",
    "jest.config.js", "jest.config.ts", "vitest.config.ts", "vitest.config.js", "setup.cfg",
}


def _login(obj: dict[str, Any] | None) -> str:
    return (obj or {}).get("login", "") or ""


def _is_bot(comment: dict[str, Any]) -> bool:
    user = comment.get("user") or {}
    return user.get("type") == "Bot" or _login(user).endswith("[bot]")


def _issue_refs(text: str, number: int) -> bool:
    if not text:
        return False
    return re.search(rf"(?<![\w/])#{number}\b", text) is not None or f"issues/{number}" in text


def spec_quality(body: str) -> int:
    body = body or ""
    score = 0
    length = len(body)
    if length > 200:
        score += 2
    if length > 600:
        score += 1
    lowered = body.lower()
    for word in ("steps to reproduce", "reproduc", "expected", "actual", "acceptance", "requirements"):
        if word in lowered:
            score += 1
    if "```" in body:
        score += 1
    if CHECKBOX_RE.search(body):
        score += 1
    return min(score, 10)


def extract_conditions(issue_body: str, comments: list[dict[str, Any]], platform: str, number: int) -> list[str]:
    conditions: list[str] = []
    for m in CHECKBOX_RE.finditer(issue_body or ""):
        conditions.append(m.group(1).strip())
    for line in (issue_body or "").splitlines():
        stripped = line.strip(" -*>")
        if 15 < len(stripped) < 220 and any(h in stripped.lower() for h in CONDITION_HINTS):
            conditions.append(stripped)
    for c in comments:
        if _is_bot(c):
            for line in (c.get("body") or "").splitlines():
                stripped = line.strip(" -*>")
                if 15 < len(stripped) < 220 and any(h in stripped.lower() for h in CONDITION_HINTS):
                    conditions.append(stripped)
    if platform == "algora":
        conditions.append(f"Algora : inclure `/claim #{number}` dans le corps de la PR ; paiement après fusion.")
    seen: set[str] = set()
    unique = []
    for c in conditions:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:12]


def analyze_data(b: Bounty, cfg: dict[str, Any], repo: dict[str, Any] | None,
                 issue: dict[str, Any] | None, comments: list[dict[str, Any]],
                 pulls: list[dict[str, Any]], rewarded_count: int | None = None,
                 root_entries: list[str] | None = None) -> Analysis:
    """Analyse pure (sans réseau) à partir des données GitHub déjà chargées."""
    profil = cfg["profil"]
    a = Analysis()
    issue = issue or {}
    repo = repo or {}
    body = issue.get("body") or b.body or ""

    # Montant : commentaire de bot (Algora) > labels > titre > corps
    bot_amount = None
    for c in comments:
        if _is_bot(c) and BOT_BOUNTY_RE.search(c.get("body") or ""):
            a.bot_bounty_comment = True
            amt = parse_amount(c.get("body") or "")
            if amt and (bot_amount is None or amt > bot_amount):
                bot_amount = amt
    labels = [l.get("name", "") if isinstance(l, dict) else str(l) for l in issue.get("labels", [])] or b.labels
    a.amount_usd = bot_amount or parse_amount(" ".join(labels)) or parse_amount(issue.get("title", "")) \
        or parse_amount(body) or b.amount_usd

    # Concurrence : /attempt, /claim et PR liées
    claimants: list[str] = []
    for c in comments:
        if _is_bot(c):
            continue
        text = c.get("body") or ""
        if CLAIM_RE.search(text) or PR_MENTION_RE.search(text):
            login = _login(c.get("user"))
            if login and login not in claimants:
                claimants.append(login)
    a.claims = len(claimants)
    a.claimants = claimants[:20]
    for pr in pulls:
        text = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
        if not _issue_refs(text, b.number):
            continue
        if pr.get("merged_at"):
            a.linked_prs_merged += 1
        elif pr.get("state") == "open":
            a.linked_prs_open += 1
        else:
            a.linked_prs_closed += 1

    # Dépôt
    a.repo_stars = repo.get("stargazers_count")
    a.repo_is_fork = bool(repo.get("fork"))
    a.repo_archived = bool(repo.get("archived"))
    a.repo_language = repo.get("language") or b.language
    a.repo_pushed_at = repo.get("pushed_at")
    a.repo_rewarded_before = rewarded_count
    if root_entries is not None:
        a.tests_present = any(entry in TEST_MARKERS for entry in root_entries)

    # Issue
    created = parse_iso(issue.get("created_at") or b.created_at)
    if created:
        a.age_days = round((datetime.now(timezone.utc) - created).total_seconds() / 86400, 1)
    a.assigned = bool(issue.get("assignees") or issue.get("assignee") or b.assignees)
    a.spec_quality = spec_quality(body)
    platform = b.platform if b.platform != "inconnu" else ("algora" if a.bot_bounty_comment else b.platform)
    a.conditions = extract_conditions(body, comments, platform, b.number)
    state = issue.get("state") or b.state

    # ----------------------------------------------------------------- score
    score = 50.0
    reasons: list[str] = []
    flags: list[str] = []
    if state != "open":
        flags.append(f"issue {state}")
    if a.repo_is_fork:
        flags.append("dépôt = fork (labels copiés, prime inexistante)")
    if a.repo_archived:
        flags.append("dépôt archivé")
    if a.assigned:
        flags.append("issue déjà assignée")
    if a.linked_prs_merged:
        flags.append(f"{a.linked_prs_merged} PR déjà fusionnée(s) pour cette issue")
    if a.claims > int(profil.get("claims_max", 2)):
        flags.append(f"{a.claims} personnes ont déjà réclamé la tâche (/attempt, /claim, PR)")
    if a.linked_prs_open > int(profil.get("prs_ouvertes_max", 1)):
        flags.append(f"{a.linked_prs_open} PR ouvertes concurrentes")
    if a.amount_usd is None:
        flags.append("montant introuvable (prime non confirmée par un bot ou un label)")
    elif a.amount_usd < float(profil.get("montant_min", 0)):
        flags.append(f"montant {a.amount_usd:.0f} $ sous le minimum")
    lowered_labels = [l.lower() for l in labels]
    for bad in cfg["sources"].get("exclure_labels", []):
        if any(bad.lower() in label for label in lowered_labels):
            flags.append(f"label exclu : {bad}")

    if a.amount_usd:
        bonus = min(a.amount_usd, 500) / 500 * 20
        score += bonus
        reasons.append(f"montant {a.amount_usd:.0f} $ (+{bonus:.0f})")
    if a.bot_bounty_comment:
        score += 10
        reasons.append("prime confirmée par un bot de plateforme (+10)")
    if rewarded_count:
        score += 15
        reasons.append(f"le dépôt a déjà payé {rewarded_count} prime(s) (+15)")
    elif rewarded_count == 0:
        reasons.append("aucune prime payée connue dans ce dépôt (0)")
    if a.repo_stars is not None:
        star_bonus = min(10.0, math.log10(a.repo_stars + 1) * 3)
        score += star_bonus
        reasons.append(f"{a.repo_stars} étoiles (+{star_bonus:.0f})")
    langs = {l.lower() for l in profil.get("langages", [])}
    if a.repo_language and a.repo_language.lower() in langs:
        score += 10
        reasons.append(f"langage {a.repo_language} dans le profil (+10)")
    elif a.repo_language:
        score -= 10
        reasons.append(f"langage {a.repo_language} hors profil (-10)")
    score += a.spec_quality
    reasons.append(f"qualité de la spécification {a.spec_quality}/10 (+{a.spec_quality})")
    if a.tests_present:
        score += 5
        reasons.append("suite de tests présente (+5)")
    elif a.tests_present is False:
        score -= 5
        reasons.append("pas de suite de tests visible (-5)")
    penalty = a.claims * 10 + a.linked_prs_open * 15
    if penalty:
        score -= penalty
        reasons.append(f"concurrence : {a.claims} réclamation(s), {a.linked_prs_open} PR ouverte(s) (-{penalty})")
    if a.age_days is not None:
        if a.age_days > 180:
            score -= 20
            reasons.append(f"issue âgée de {a.age_days:.0f} j (-20)")
        elif a.age_days > 90:
            score -= 10
            reasons.append(f"issue âgée de {a.age_days:.0f} j (-10)")
        elif a.age_days < 3:
            score += 5
            reasons.append("issue très récente, peu de concurrence probable (+5)")
    pushed = parse_iso(a.repo_pushed_at)
    if pushed and (datetime.now(timezone.utc) - pushed).days > 90:
        score -= 15
        reasons.append("dépôt sans activité depuis plus de 90 j (-15)")

    a.score = round(max(0.0, min(100.0, score)), 1)
    a.reasons = reasons
    a.red_flags = flags
    if flags:
        a.verdict = "NON"
    elif a.score >= 60:
        a.verdict = "GO"
    elif a.score >= 40:
        a.verdict = "PRUDENCE"
    else:
        a.verdict = "NON"
    return a


def analyze_live(client: GitHubClient, b: Bounty, cfg: dict[str, Any], log=print) -> Analysis:
    """Charge les données GitHub (dépôt, issue, commentaires, PR) puis analyse."""
    repo = client.repo(b.owner, b.repo)
    issue = client.issue(b.owner, b.repo, b.number)
    comments = client.issue_comments(b.owner, b.repo, b.number)
    pulls: list[dict[str, Any]] = []
    try:
        pulls = client.pulls(b.owner, b.repo, state="all", max_pages=2)
    except GitHubError as exc:
        log(f"  ! liste des PR indisponible : {exc}")
    # PR liées via la timeline (références croisées), plus fiable que le texte des PR.
    try:
        for event in client.issue_timeline(b.owner, b.repo, b.number):
            if event.get("event") != "cross-referenced":
                continue
            src = (event.get("source") or {}).get("issue") or {}
            if src.get("pull_request") and src.get("number"):
                if not any(p.get("number") == src["number"] for p in pulls):
                    pulls.append({
                        "number": src["number"],
                        "title": src.get("title", ""),
                        "body": f"#{b.number}",
                        "state": src.get("state"),
                        "merged_at": (src.get("pull_request") or {}).get("merged_at"),
                    })
    except GitHubError as exc:
        log(f"  ! timeline indisponible : {exc}")
    rewarded: int | None = None
    try:
        rewarded = len(client.repo_issues(b.owner, b.repo, labels="💰 Rewarded", state="closed", per_page=20))
    except GitHubError:
        rewarded = None
    root_entries: list[str] | None = None
    try:
        listing = client.contents(b.owner, b.repo, "")
        if isinstance(listing, list):
            root_entries = [entry.get("name", "") for entry in listing]
    except GitHubError:
        root_entries = None
    # Mise à jour de la prime avec les données fraîches
    b.title = issue.get("title", b.title)
    b.body = (issue.get("body") or b.body or "")[:4000]
    b.labels = [l.get("name", "") for l in issue.get("labels", [])] or b.labels
    b.created_at = issue.get("created_at", b.created_at)
    b.updated_at = issue.get("updated_at", b.updated_at)
    b.state = issue.get("state", b.state)
    b.comments_count = int(issue.get("comments", b.comments_count) or 0)
    b.assignees = [a.get("login", "") for a in issue.get("assignees", []) or []]
    b.language = repo.get("language") or b.language
    analysis = analyze_data(b, cfg, repo, issue, comments, pulls, rewarded, root_entries)
    if b.platform == "inconnu" and analysis.bot_bounty_comment:
        b.platform = "algora"
    if analysis.amount_usd and not b.amount_usd:
        b.amount_usd = analysis.amount_usd
    return analysis


# ------------------------------------------------------------------ dossier
def render_dossier(item: PipelineItem) -> str:
    b, a = item.bounty, item.analysis
    lines = [f"# Prime {b.key}", "", f"**{b.title}**  ", f"{b.url}", ""]
    lines += [
        "| Champ | Valeur |", "|---|---|",
        f"| Montant | {f'{a.amount_usd:.0f} $' if a and a.amount_usd else 'inconnu'} |",
        f"| Plateforme | {b.platform} |",
        f"| Langage | {(a.repo_language if a else None) or b.language or '?'} |",
        f"| Étape | {item.stage.value} |",
        f"| Intervention attendue | {item.checkpoint or '-'} |",
    ]
    if a:
        lines += [
            f"| Verdict | **{a.verdict}** (score {a.score}/100) |",
            f"| Âge de l'issue | {a.age_days if a.age_days is not None else '?'} j |",
            f"| Concurrence | {a.claims} réclamation(s), {a.linked_prs_open} PR ouverte(s), {a.linked_prs_merged} fusionnée(s) |",
            f"| Dépôt | {a.repo_stars if a.repo_stars is not None else '?'} étoiles, primes payées : {a.repo_rewarded_before if a.repo_rewarded_before is not None else '?'} |",
            f"| Tests | {'présents' if a.tests_present else ('absents' if a.tests_present is False else '?')} |",
            "",
        ]
        if a.red_flags:
            lines.append("## Signaux d'alerte")
            lines += [f"- {f}" for f in a.red_flags]
            lines.append("")
        lines.append("## Détail du score")
        lines += [f"- {r}" for r in a.reasons]
        lines.append("")
        if a.claimants:
            lines.append("## Concurrents identifiés")
            lines.append(", ".join(a.claimants))
            lines.append("")
        lines.append("## Conditions à respecter")
        lines += [f"- {c}" for c in a.conditions] or ["- (aucune condition explicite trouvée : relire l'issue)"]
        lines.append("")
    lines.append("## Demande (extrait)")
    lines.append("")
    lines.append((b.body or "(corps vide)")[:2500])
    lines.append("")
    lines.append("## Pipeline")
    lines.append("")
    lines.append("| Étape | Travail automatisé | Intervention de l'utilisateur |")
    lines.append("|---|---|---|")
    for stage, work in PIPELINE_WORK.items():
        marker = "➡️ " if stage == item.stage else ""
        lines.append(f"| {marker}{stage.value} | {work} | {CHECKPOINTS[stage]} |")
    lines.append("")
    if item.history:
        lines.append("## Historique")
        lines += [f"- {h['at']} [{h['stage']}] {h['note']}" for h in item.history]
        lines.append("")
    return "\n".join(lines)
