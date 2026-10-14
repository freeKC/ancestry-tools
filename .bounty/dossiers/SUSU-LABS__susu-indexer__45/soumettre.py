#!/usr/bin/env python3
"""Soumet la PR de la prime SUSU-LABS/susu-indexer#45 depuis le compte freeKC.

Étapes : fork (ou réutilisation du fork existant), clone, application du
correctif, tests facultatifs, poussée de la branche sur le fork, ouverture de
la PR, commentaire facultatif sur l'issue.

Le jeton est lu dans un fichier (ou dans la variable GITHUB_TOKEN). Il n'est
jamais affiché, jamais écrit sur disque, jamais passé en argument de commande :
git le reçoit par une variable d'environnement via GIT_ASKPASS, avec les
gestionnaires d'identifiants désactivés pour qu'il ne soit pas mémorisé.

Usage :
    python3 soumettre.py --jeton CHEMIN_DU_FICHIER_JETON
    python3 soumettre.py --jeton CHEMIN --tests          # lance aussi la suite Deno
    python3 soumettre.py --simulation                    # tout sauf fork, push et PR
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM = "SUSU-LABS/susu-indexer"
ISSUE = 45
LOGIN = "freeKC"
GIT_NAME = "FreeKC"
GIT_EMAIL = "fredrenaud25@gmail.com"
BRANCH = "fix/45-start-ledger-above-checkpoint"
BASE = "main"
TITLE = "fix(indexer): never let a raised start ledger skip past the checkpoint"
COMMENT = (
    "Opened #{number} for this. It also restores a green CI on main (format, lint, the three "
    "failing orchestration tests and the test permissions in the workflow), which overlaps with #81."
)
API = "https://api.github.com"
HERE = Path(__file__).resolve().parent
PATCH = HERE / "susu-indexer-45.patch"
BODY = HERE / "PR_BODY.md"


def read_token(path: str | None) -> str:
    if path:
        token = Path(path).expanduser().read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        sys.exit("Jeton introuvable : passer --jeton FICHIER ou définir GITHUB_TOKEN.")
    return token


def api(method: str, path: str, token: str, payload: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "prime-susu-indexer-45",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"message": raw.decode("utf-8", "replace")[:300]}


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    print("$ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"Échec (code {result.returncode}) : {' '.join(cmd)}")


def ensure_fork(token: str) -> str:
    status, data = api("POST", f"/repos/{UPSTREAM}/forks", token, {"default_branch_only": True})
    if status not in (200, 202) or not isinstance(data, dict):
        raise SystemExit(f"Fork impossible ({status}) : {data.get('message') if isinstance(data, dict) else data}")
    full_name = data["full_name"]
    print(f"Fork : https://github.com/{full_name}")
    for _ in range(40):
        status, _ = api("GET", f"/repos/{full_name}/branches/{BASE}", token)
        if status == 200:
            return full_name
        time.sleep(3)
    raise SystemExit("Le fork n'est pas encore prêt : relancer le script dans une minute.")


def existing_pull(token: str, fork_owner: str) -> dict | None:
    status, data = api("GET", f"/repos/{UPSTREAM}/pulls?state=open&head={fork_owner}:{BRANCH}&base={BASE}", token)
    if status == 200 and isinstance(data, list) and data:
        return data[0]
    return None


def prepare_clone(workdir: Path) -> Path:
    repo = workdir / "susu-indexer"
    run(["git", "clone", "--quiet", f"https://github.com/{UPSTREAM}.git", str(repo)])
    run(["git", "config", "user.name", GIT_NAME], cwd=repo)
    run(["git", "config", "user.email", GIT_EMAIL], cwd=repo)
    run(["git", "checkout", "--quiet", "-b", BRANCH, f"origin/{BASE}"], cwd=repo)
    print(f"$ git am --3way {PATCH.name}", flush=True)
    applied = subprocess.run(["git", "am", "--3way", "--quiet", str(PATCH)], cwd=repo)
    if applied.returncode != 0:
        subprocess.run(["git", "am", "--abort"], cwd=repo)
        raise SystemExit(
            f"Le correctif ne s'applique plus sur {UPSTREAM}@{BASE} (la branche amont a bougé). "
            "Me renvoyer ce message pour une version rebasée."
        )
    run(["git", "log", "--oneline", f"origin/{BASE}..HEAD"], cwd=repo)
    return repo


def run_tests(repo: Path) -> None:
    if shutil.which("deno") is None:
        print("Deno absent : tests ignorés (la PR les fera tourner en CI).")
        return
    for task in ("fmt:check", "lint", "check", "test"):
        run(["deno", "task", task], cwd=repo)


def push_branch(repo: Path, fork: str, token: str, workdir: Path) -> None:
    askpass = workdir / "askpass.sh"
    askpass.write_text(
        '#!/bin/sh\ncase "$1" in\n  Username*) printf "%s\\n" "$PRIME_GIT_USER" ;;\n'
        '  *) printf "%s\\n" "$PRIME_GIT_TOKEN" ;;\nesac\n',
        encoding="utf-8",
    )
    askpass.chmod(0o700)
    env = dict(os.environ, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT="0",
               PRIME_GIT_USER=LOGIN, PRIME_GIT_TOKEN=token)
    # credential.helper vide : le jeton n'est stocké par aucun gestionnaire d'identifiants.
    run(["git", "-c", "credential.helper=", "push", "--force", f"https://github.com/{fork}.git",
         f"{BRANCH}:{BRANCH}"], cwd=repo, env=env)


def open_pull(token: str, fork_owner: str, draft: bool) -> dict:
    body = BODY.read_text(encoding="utf-8")
    payload = {"title": TITLE, "head": f"{fork_owner}:{BRANCH}", "base": BASE, "body": body,
               "maintainer_can_modify": True, "draft": draft}
    status, data = api("POST", f"/repos/{UPSTREAM}/pulls", token, payload)
    if status != 201 or not isinstance(data, dict):
        detail = data.get("errors") or data.get("message") if isinstance(data, dict) else data
        raise SystemExit(f"Ouverture de la PR impossible ({status}) : {detail}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jeton", help="fichier contenant le jeton GitHub (une ligne)")
    parser.add_argument("--tests", action="store_true", help="lancer format, lint, typage et tests (Deno requis)")
    parser.add_argument("--brouillon", action="store_true", help="ouvrir la PR en brouillon")
    parser.add_argument("--commenter", action="store_true", help="signaler la PR sur l'issue #45")
    parser.add_argument("--simulation", action="store_true", help="ne rien créer ni pousser sur GitHub")
    parser.add_argument("--garder", action="store_true", help="conserver le clone de travail")
    args = parser.parse_args()

    for required in (PATCH, BODY):
        if not required.is_file():
            raise SystemExit(f"Fichier manquant à côté du script : {required.name}")
    token = "" if args.simulation else read_token(args.jeton)

    workdir = Path(tempfile.mkdtemp(prefix="susu45-"))
    try:
        repo = prepare_clone(workdir)
        if args.tests:
            run_tests(repo)
        if args.simulation:
            print("Simulation : correctif appliqué proprement. Rien n'a été créé ni poussé.")
            return 0

        fork = ensure_fork(token)
        fork_owner = fork.split("/")[0]
        push_branch(repo, fork, token, workdir)

        pull = existing_pull(token, fork_owner)
        if pull:
            print(f"PR déjà ouverte, branche mise à jour : {pull['html_url']}")
        else:
            pull = open_pull(token, fork_owner, args.brouillon)
            print(f"PR ouverte : {pull['html_url']}")
            if args.commenter:
                status, _ = api("POST", f"/repos/{UPSTREAM}/issues/{ISSUE}/comments", token,
                                {"body": COMMENT.format(number=pull["number"])})
                print("Commentaire publié sur l'issue." if status == 201 else f"Commentaire refusé ({status}).")
        return 0
    finally:
        if args.garder:
            print(f"Clone conservé : {workdir / 'susu-indexer'}")
            (workdir / "askpass.sh").unlink(missing_ok=True)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
