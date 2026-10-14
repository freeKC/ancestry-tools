"""Découverte des primes : recherche GitHub (API ou page HTML), Algora, import JSON."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .github import GitHubClient, GitHubError, ScopeError
from .models import ISSUE_URL_RE, Bounty, now_iso, parse_iso

AMOUNT_RES = [
    # "$50", "$ 1,000", "$1.2k"
    re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?([kK])?(?![\w.])"),
    # "100 USD", "100 dollars"
    re.compile(r"(\d[\d,]*(?:\.\d+)?)\s?(USD|usd|US\$|dollars?)\b"),
    # "/bounty 75", "/bounty $1k"
    re.compile(r"/bounty\s+\$?(\d[\d,]*(?:\.\d+)?)\s?([kK])?", re.I),
]


def parse_amount(text: str | None) -> float | None:
    """Montant maximal en dollars trouvé dans un texte (une prime peut être augmentée)."""
    if not text:
        return None
    best: float | None = None
    for rx in AMOUNT_RES:
        for m in rx.finditer(text):
            try:
                value = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            suffix = m.group(2) if rx.groups >= 2 else None
            if suffix and suffix.lower() == "k":
                value *= 1000
            if best is None or value > best:
                best = value
    return best


def detect_platform(labels: Iterable[str], text: str = "") -> str:
    lowered = {label.lower() for label in labels}
    text_l = (text or "").lower()
    if "💎 bounty" in lowered or "algora" in text_l:
        return "algora"
    if "opire" in text_l:
        return "opire"
    if "polar.sh" in text_l or "polar" in lowered:
        return "polar"
    if any("bounty" in label or "reward" in label for label in lowered):
        return "label"
    return "inconnu"


# ------------------------------------------------------------------ requêtes
def build_queries(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Requêtes de recherche GitHub (une par label x langage), avec URL API et URL HTML."""
    src = cfg["sources"]
    profil = cfg["profil"]
    cutoff = (date.today() - timedelta(days=int(src.get("recherche_jours", 90)))).isoformat()
    exclusions = " ".join(f"-user:{owner}" for owner in src.get("exclure_proprietaires", [])[:4])
    languages: list[str | None] = list(profil.get("langages") or []) or [None]
    queries = []
    for label in src.get("github_labels", []):
        for lang in languages:
            q = f'label:"{label}" is:issue is:open created:>{cutoff}'
            if lang:
                q += f" language:{lang}"
            if exclusions:
                q += f" {exclusions}"
            html = "https://github.com/search?" + urllib.parse.urlencode(
                {"q": q, "type": "issues", "s": "created", "o": "desc"})
            queries.append({"label": label, "language": lang, "q": q, "html_url": html})
    return queries


def _issue_from_api(item: dict[str, Any], language: str | None, source: str) -> Bounty | None:
    repo_url = item.get("repository_url", "")
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        m = ISSUE_URL_RE.search(item.get("html_url", ""))
        if not m:
            return None
        owner, repo = m.group("owner"), m.group("repo")
    else:
        owner, repo = parts[-2], parts[-1]
    labels = [l.get("name", "") if isinstance(l, dict) else str(l) for l in item.get("labels", [])]
    body = item.get("body") or ""
    amount = parse_amount(item.get("title", "")) or parse_amount(" ".join(labels)) or parse_amount(body)
    return Bounty(
        owner=owner,
        repo=repo,
        number=int(item["number"]),
        title=item.get("title", ""),
        amount_usd=amount,
        platform=detect_platform(labels, body),
        labels=labels,
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
        language=language,
        state=item.get("state", "open"),
        assignees=[a.get("login", "") for a in item.get("assignees", []) or []],
        comments_count=int(item.get("comments", 0) or 0),
        body=body[:4000],
        source=source,
    )


def search_github_api(client: GitHubClient, cfg: dict[str, Any], max_pages: int | None = None,
                      log=print) -> list[Bounty]:
    """Recherche via l'API GitHub. Lève ScopeError dans un environnement restreint."""
    pages = max_pages or int(cfg["sources"].get("pages_max", 3))
    found: dict[str, Bounty] = {}
    for query in build_queries(cfg):
        for page in range(1, pages + 1):
            try:
                result = client.search_issues(query["q"], per_page=50, page=page)
            except ScopeError:
                raise
            except GitHubError as exc:
                log(f"  ! requête {query['q']!r} page {page} : {exc}")
                break
            items = result.get("items", []) if isinstance(result, dict) else []
            for item in items:
                b = _issue_from_api(item, query["language"], source=f"github-search:{query['label']}")
                if b and b.key not in found:
                    found[b.key] = b
            if len(items) < 50:
                break
    return list(found.values())


# -------------------------------------------------------------------- import
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json_array(text: str) -> list[Any]:
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Aucun tableau JSON trouvé dans le texte importé.")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("Le JSON importé n'est pas un tableau.")
    return data


def _coerce_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_amount(str(value))


def import_results(text: str, source: str = "import", language: str | None = None) -> list[Bounty]:
    """Convertit une liste JSON (par ex. relevée sur une page de recherche GitHub).

    Clés tolérées par élément : repo ("owner/name") ou issue_url/url, number/issue_number,
    title, labels, amount, created/created_at, snippet/body, language, state.
    """
    bounties: list[Bounty] = []
    for raw in _extract_json_array(text):
        if not isinstance(raw, dict):
            continue
        owner = repo = None
        number = raw.get("number", raw.get("issue_number"))
        url = raw.get("issue_url") or raw.get("url") or raw.get("html_url") or ""
        m = ISSUE_URL_RE.search(str(url))
        if m:
            owner, repo, number = m.group("owner"), m.group("repo"), int(m.group("number"))
        elif raw.get("repo") and "/" in str(raw["repo"]):
            owner, repo = str(raw["repo"]).split("/", 1)
        if not owner or not repo or number in (None, ""):
            continue
        labels = raw.get("labels") or []
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",") if l.strip()]
        body = raw.get("snippet") or raw.get("body") or ""
        title = raw.get("title", "")
        amount = _coerce_amount(raw.get("amount")) or parse_amount(title) or parse_amount(" ".join(labels)) \
            or parse_amount(body)
        created = raw.get("created_at") or raw.get("created")
        created_iso = created if parse_iso(str(created)) else None
        b = Bounty(
            owner=owner.strip(),
            repo=repo.strip(),
            number=int(number),
            title=title,
            amount_usd=amount,
            platform=detect_platform(labels, f"{title} {body}"),
            labels=list(labels),
            created_at=created_iso,
            language=raw.get("language") or language,
            state=raw.get("state") or "open",
            body=str(body)[:4000],
            source=source,
        )
        if created and not created_iso:
            b.prescore_notes.append(f"créée : {created}")
        bounties.append(b)
    return bounties


# -------------------------------------------------------------------- Algora
def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def parse_algora_payload(payload: Any, amount_in_cents: bool = True) -> list[Bounty]:
    """Extraction tolérante : tout objet contenant une URL d'issue GitHub et un montant."""
    found: dict[str, Bounty] = {}
    for node in _walk(payload):
        url = None
        for value in node.values():
            if isinstance(value, str) and ISSUE_URL_RE.search(value):
                url = value
                break
        if not url:
            continue
        amount = None
        for key, value in node.items():
            if "reward" in key.lower() or "amount" in key.lower():
                if isinstance(value, dict):
                    value = value.get("amount")
                if isinstance(value, (int, float)):
                    amount = float(value) / (100 if amount_in_cents else 1)
                    break
        if amount is None:
            continue
        b = Bounty.from_ref(url, title=str(node.get("title") or node.get("name") or ""),
                            amount_usd=amount, platform="algora", source="algora-api")
        found.setdefault(b.key, b)
    return list(found.values())


def fetch_algora(cfg: dict[str, Any], limit: int = 100, timeout: int = 30) -> list[Bounty]:
    """Appel direct à l'API Algora (indisponible dans un réseau restreint)."""
    api = cfg["sources"].get("algora_api")
    if not api:
        return []
    params = urllib.parse.urlencode({"input": json.dumps({"json": {"limit": limit, "status": "open"}})})
    req = urllib.request.Request(f"{api}?{params}", headers={"User-Agent": "bounty-pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_algora_payload(payload, amount_in_cents=bool(cfg["sources"].get("algora_montant_en_cents", True)))


# --------------------------------------------------------------- pré-filtre
def prefilter(b: Bounty, cfg: dict[str, Any]) -> list[str]:
    """Raisons d'exclusion rapides, calculables sans appel réseau (vide = conservée)."""
    src, profil = cfg["sources"], cfg["profil"]
    reasons: list[str] = []
    if b.owner.lower() in {o.lower() for o in src.get("exclure_proprietaires", [])}:
        reasons.append(f"propriétaire exclu ({b.owner})")
    lowered = [label.lower() for label in b.labels]
    for bad in src.get("exclure_labels", []):
        if any(bad.lower() in label for label in lowered):
            reasons.append(f"label exclu ({bad})")
    haystack = f"{b.title}\n{b.body}".lower()
    for word in src.get("exclure_mots", []):
        if word.lower() in haystack:
            reasons.append(f"mot exclu ({word})")
    if b.state and b.state != "open":
        reasons.append(f"issue {b.state}")
    if b.amount_usd is not None:
        if b.amount_usd < float(profil.get("montant_min", 0)):
            reasons.append(f"montant trop bas ({b.amount_usd:.0f} $)")
        if b.amount_usd > float(profil.get("montant_max", 1e9)):
            reasons.append(f"montant trop élevé ({b.amount_usd:.0f} $)")
    langs = {l.lower() for l in profil.get("langages", [])}
    if b.language and langs and b.language.lower() not in langs:
        reasons.append(f"langage hors profil ({b.language})")
    created = parse_iso(b.created_at)
    if created:
        age = (datetime.now(timezone.utc) - created).days
        if age > int(profil.get("age_max_jours", 120)):
            reasons.append(f"trop ancienne ({age} j)")
    if b.assignees:
        reasons.append(f"déjà assignée ({', '.join(b.assignees)})")
    return reasons


def prescore(b: Bounty, cfg: dict[str, Any]) -> float:
    """Score rapide (0-100) pour classer les candidates avant l'analyse complète."""
    score = 40.0
    if b.amount_usd:
        score += min(b.amount_usd, 500) / 500 * 25
    if b.platform == "algora":
        score += 10
    elif b.platform in ("opire", "polar"):
        score += 6
    created = parse_iso(b.created_at)
    if created:
        age = (datetime.now(timezone.utc) - created).days
        score += max(0.0, 15 - age / 4)  # fraîcheur : 15 pts le premier jour, 0 au bout de 60 j
    if b.comments_count > 10:
        score -= min(20.0, (b.comments_count - 10) * 1.5)  # beaucoup de bruit = concurrence probable
    if b.language and b.language.lower() in {l.lower() for l in cfg["profil"].get("langages", [])}:
        score += 5
    if len(b.body) > 300:
        score += 5
    return round(max(0.0, min(100.0, score)), 1)


def dedupe(bounties: Iterable[Bounty]) -> list[Bounty]:
    seen: dict[str, Bounty] = {}
    for b in bounties:
        current = seen.get(b.key)
        if current is None:
            seen[b.key] = b
        else:  # fusion : on garde les champs renseignés
            for name in ("title", "amount_usd", "created_at", "language", "body"):
                if not getattr(current, name) and getattr(b, name):
                    setattr(current, name, getattr(b, name))
            current.labels = sorted(set(current.labels) | set(b.labels))
    return list(seen.values())


def discovery_plan(cfg: dict[str, Any]) -> str:
    """Texte décrivant comment découvrir des primes quand l'API n'est pas accessible."""
    lines = [
        "Recherche GitHub indisponible depuis cet environnement : ouvrir les URL ci-dessous,",
        "relever chaque résultat en JSON (repo, number, title, labels, created, amount, snippet),",
        "l'enregistrer dans un fichier puis lancer `python -m bounty import FICHIER`.",
        "",
    ]
    for query in build_queries(cfg):
        lines.append(f"- [{query['label']} / {query['language'] or 'tous langages'}] {query['html_url']}")
    lines.append("")
    lines.append(f"Dernière mise à jour du plan : {now_iso()}")
    return "\n".join(lines)
