"""Client GitHub REST minimal (bibliothèque standard uniquement)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import __version__

USER_AGENT = f"bounty-pipeline/{__version__}"


class GitHubError(Exception):
    def __init__(self, status: int, message: str, url: str = ""):
        super().__init__(f"GitHub {status}: {message} ({url})")
        self.status = status
        self.message = message
        self.url = url


class ScopeError(GitHubError):
    """Le point d'accès est hors du périmètre autorisé par l'environnement.

    Cas d'un environnement dont l'accès GitHub est limité à certains dépôts : la
    découverte passe alors par la recherche HTML de GitHub (commande ``import``)
    et l'analyse d'un dépôt exige qu'il soit rendu accessible à l'environnement.
    """


SCOPE_MARKERS = (
    "bound to their configured repositories",
    "not enabled for this session",
)


class GitHubClient:
    def __init__(self, token: str | None = None, api: str = "https://api.github.com", timeout: int = 30):
        self.token = token
        self.api = api.rstrip("/")
        self.timeout = timeout
        self.last_headers: dict[str, str] = {}

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, params: dict[str, Any] | None = None,
                 body: dict[str, Any] | None = None, retries: int = 2) -> Any:
        url = path if path.startswith("http") else f"{self.api}/{path.lstrip('/')}"
        if params:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(params, doseq=True)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self.last_headers = dict(resp.headers.items())
                    raw = resp.read()
                    return json.loads(raw.decode("utf-8")) if raw else None
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    payload = {"message": raw.decode("utf-8", "replace")[:300]}
                message = payload.get("message", "") if isinstance(payload, dict) else str(payload)
                if exc.code in (403, 429) and "rate limit" in message.lower() and attempt < retries:
                    attempt += 1
                    time.sleep(2 ** attempt)
                    continue
                if any(marker in message for marker in SCOPE_MARKERS):
                    raise ScopeError(exc.code, message, url) from None
                raise GitHubError(exc.code, message, url) from None
            except urllib.error.URLError as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(2 ** attempt)
                    continue
                raise GitHubError(0, f"réseau : {exc.reason}", url) from None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("POST", path, body=body)

    def paginate(self, path: str, params: dict[str, Any] | None = None, max_pages: int = 3,
                 per_page: int = 100) -> list[Any]:
        out: list[Any] = []
        params = dict(params or {})
        params["per_page"] = per_page
        for page in range(1, max_pages + 1):
            params["page"] = page
            chunk = self.get(path, params)
            if not chunk:
                break
            out.extend(chunk)
            if len(chunk) < per_page:
                break
        return out

    # --------------------------------------------------------------- lecture
    def rate_limit(self) -> dict[str, Any]:
        return self.get("rate_limit")

    def repo(self, owner: str, repo: str) -> dict[str, Any]:
        return self.get(f"repos/{owner}/{repo}")

    def issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self.get(f"repos/{owner}/{repo}/issues/{number}")

    def issue_comments(self, owner: str, repo: str, number: int, max_pages: int = 3) -> list[dict[str, Any]]:
        return self.paginate(f"repos/{owner}/{repo}/issues/{number}/comments", max_pages=max_pages)

    def issue_timeline(self, owner: str, repo: str, number: int, max_pages: int = 3) -> list[dict[str, Any]]:
        return self.paginate(f"repos/{owner}/{repo}/issues/{number}/timeline", max_pages=max_pages)

    def pulls(self, owner: str, repo: str, state: str = "all", max_pages: int = 2) -> list[dict[str, Any]]:
        return self.paginate(f"repos/{owner}/{repo}/pulls",
                             {"state": state, "sort": "updated", "direction": "desc"}, max_pages=max_pages)

    def pull(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self.get(f"repos/{owner}/{repo}/pulls/{number}")

    def repo_issues(self, owner: str, repo: str, **params: Any) -> list[dict[str, Any]]:
        return self.get(f"repos/{owner}/{repo}/issues", params) or []

    def contents(self, owner: str, repo: str, path: str = "") -> Any:
        return self.get(f"repos/{owner}/{repo}/contents/{path}".rstrip("/"))

    def search_issues(self, query: str, sort: str = "created", order: str = "desc",
                      per_page: int = 50, page: int = 1) -> dict[str, Any]:
        return self.get("search/issues",
                        {"q": query, "sort": sort, "order": order, "per_page": per_page, "page": page})

    def me(self) -> dict[str, Any]:
        return self.get("user")

    # -------------------------------------------------------------- écriture
    def fork(self, owner: str, repo: str) -> dict[str, Any]:
        return self.post(f"repos/{owner}/{repo}/forks", {})

    def create_pull(self, owner: str, repo: str, title: str, head: str, base: str, body: str,
                    draft: bool = False) -> dict[str, Any]:
        return self.post(f"repos/{owner}/{repo}/pulls",
                         {"title": title, "head": head, "base": base, "body": body, "draft": draft})

    def comment(self, owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
        return self.post(f"repos/{owner}/{repo}/issues/{number}/comments", {"body": body})


def search_available(client: GitHubClient) -> tuple[bool, str]:
    """Teste si la recherche globale est autorisée (faux dans un environnement restreint)."""
    try:
        client.search_issues('label:"💎 Bounty" is:issue is:open', per_page=1)
        return True, "recherche GitHub disponible"
    except ScopeError as exc:
        return False, f"recherche GitHub hors périmètre de la session : {exc.message}"
    except GitHubError as exc:
        return False, f"recherche GitHub indisponible : {exc}"
