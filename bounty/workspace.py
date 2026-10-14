"""Espace de travail : clonage, branche, détection de la pile technique, tests, brief."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import resolve
from .models import Bounty, PipelineItem, VerifyResult, now_iso


def slugify(text: str, maxlen: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:maxlen].rstrip("-") or "tache"


def run(cmd: str, cwd: Path | str, timeout: int = 1800, env: dict[str, str] | None = None) -> VerifyResult:
    """Exécute une commande shell et capture la fin de sa sortie."""
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
                              timeout=timeout, env=env)
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = f"TIMEOUT après {timeout}s\n{(exc.stdout or '')[-2000:] if isinstance(exc.stdout, str) else ''}"
        code = 124
    duration = round(time.monotonic() - start, 1)
    return VerifyResult(command=cmd, returncode=code, duration_s=duration, output_tail=output[-4000:])


def git(args: list[str], cwd: Path | str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} a échoué : {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def workspace_dir(b: Bounty, cfg: dict[str, Any]) -> Path:
    return resolve(cfg, cfg["workspace"]["dossier"]) / f"{b.owner}__{b.repo}"


def clone_repo(b: Bounty, cfg: dict[str, Any], log=print) -> Path:
    dest = workspace_dir(b, cfg)
    url = f"https://github.com/{b.owner}/{b.repo}.git"
    if (dest / ".git").is_dir():
        log(f"  dépôt déjà cloné : {dest} (git fetch)")
        git(["fetch", "origin", "--prune"], dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        log(f"  git clone {url} -> {dest}")
        git(["clone", "--quiet", url, str(dest)], dest.parent)
    return dest


def default_branch(path: Path) -> str:
    try:
        ref = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], path)
        return ref.split("/", 1)[1] if "/" in ref else ref
    except RuntimeError:
        for name in ("main", "master"):
            if git(["branch", "-r", "--list", f"origin/{name}"], path, check=False):
                return name
        return "main"


def create_branch(path: Path, name: str, base: str) -> None:
    """Crée la branche depuis ``origin/base``, ou la reprend telle quelle si elle existe déjà."""
    if git(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}"], path, check=False):
        git(["checkout", "--quiet", name], path)
    else:
        git(["checkout", "--quiet", "-b", name, f"origin/{base}"], path)


def set_identity(path: Path, name: str | None, email: str | None) -> str | None:
    """Fixe l'identité git locale du clone ; renvoie l'identité appliquée."""
    if name:
        git(["config", "user.name", name], path)
    if email:
        git(["config", "user.email", email], path)
    if not (name or email):
        return None
    current_name = git(["config", "user.name"], path, check=False)
    current_email = git(["config", "user.email"], path, check=False)
    return f"{current_name} <{current_email}>"


def branch_name(b: Bounty) -> str:
    return f"bounty/{b.number}-{slugify(b.title)}"


# ------------------------------------------------------------ pile technique
def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def detect_stack(path: Path) -> dict[str, Any]:
    """Devine les commandes d'installation, de test et de lint du dépôt."""
    stack: list[str] = []
    install: list[str] = []
    test: list[str] = []
    lint: list[str] = []
    notes: list[str] = []
    names = {p.name for p in path.iterdir()} if path.is_dir() else set()

    if "package.json" in names:
        pkg = _read_json(path / "package.json")
        scripts = pkg.get("scripts", {}) or {}
        if "pnpm-lock.yaml" in names:
            pm = "pnpm"
        elif "yarn.lock" in names:
            pm = "yarn"
        elif "bun.lockb" in names or "bun.lock" in names:
            pm = "bun"
        else:
            pm = "npm"
        stack.append(f"node/{pm}")
        install.append(f"{pm} install" + (" --frozen-lockfile" if pm == "pnpm" else ""))
        run_prefix = f"{pm} run" if pm != "yarn" else "yarn"
        if "test" in scripts:
            test.append(f"{pm} test" if pm in ("npm", "yarn", "bun") else f"{run_prefix} test")
        for script in ("typecheck", "type-check", "check-types", "lint", "format:check"):
            if script in scripts:
                lint.append(f"{run_prefix} {script}")
        if "build" in scripts and not test:
            test.append(f"{run_prefix} build")
            notes.append("pas de script test : le build sert de vérification minimale")
    if names & {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pytest.ini", "tox.ini"}:
        stack.append("python")
        if "pyproject.toml" in names or "setup.py" in names:
            install.append("python -m pip install -e .")
        for req in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt", "dev-requirements.txt",
                    "requirements/dev.txt"):
            if (path / req).is_file():
                install.append(f"python -m pip install -r {req}")
        has_tests = bool(names & {"tests", "test", "pytest.ini", "conftest.py", "tox.ini"})
        pyproject = (path / "pyproject.toml").read_text(encoding="utf-8", errors="replace") \
            if "pyproject.toml" in names else ""
        if has_tests or "pytest" in pyproject:
            install.append("python -m pip install pytest")
            test.append("python -m pytest -q")
        else:
            test.append("python -m unittest discover -v")
            notes.append("aucun dossier de tests détecté : unittest discover par défaut")
        if "ruff" in pyproject or "ruff.toml" in names:
            lint.append("ruff check .")
    if names & {"deno.json", "deno.jsonc"}:
        stack.append("deno")
        deno_cfg = _read_json(path / ("deno.json" if "deno.json" in names else "deno.jsonc"))
        tasks = deno_cfg.get("tasks", {}) or {}
        if "check" in tasks:
            lint.append("deno task check")
        for task in ("fmt:check", "lint"):
            if task in tasks:
                lint.append(f"deno task {task}")
        test.append("deno task test" if "test" in tasks else "deno test -A")
    if "go.mod" in names:
        stack.append("go")
        test.append("go build ./... && go test ./...")
        lint.append("go vet ./...")
    if "Cargo.toml" in names:
        stack.append("rust")
        test.append("cargo test")
        lint.append("cargo clippy --all-targets -- -D warnings")
    if "Makefile" in names and not test:
        makefile = (path / "Makefile").read_text(encoding="utf-8", errors="replace")
        if re.search(r"^test:", makefile, re.M):
            stack.append("make")
            test.append("make test")
    if not stack:
        notes.append("pile non reconnue : définir les commandes avec `verify --cmd`")
    return {"stack": stack, "install": install, "test": test, "lint": lint, "notes": notes,
            "detected_at": now_iso()}


# ----------------------------------------------------------------- brief
def write_brief(item: PipelineItem, path: Path, cfg: dict[str, Any]) -> Path:
    b, a = item.bounty, item.analysis
    stack = item.stack or {}
    lines = [
        f"# Brief de résolution : {b.key}",
        "",
        f"Issue : {b.url}",
        f"Titre : {b.title}",
        f"Montant : {f'{a.amount_usd:.0f} $' if a and a.amount_usd else (f'{b.amount_usd:.0f} $' if b.amount_usd else 'inconnu')}",
        f"Plateforme : {b.platform}",
        f"Branche : {item.branch} (base : {item.base_branch})",
        "",
        "## Règles",
        "- Lire d'abord CONTRIBUTING / README / les tests existants du dépôt.",
        "- Reproduire le problème avant de corriger (test qui échoue, puis qui passe).",
        "- Diff minimal, dans le style du dépôt ; pas de changement hors périmètre.",
        "- Ajouter ou adapter des tests ; ne jamais désactiver un test.",
        "- Noter chaque point ambigu dans `.bounty/dossiers/<clé>.md` (section Arbitrages) et",
        "  s'arrêter pour demander à l'utilisateur quand une interprétation change le résultat.",
        "",
        "## Conditions relevées",
    ]
    lines += [f"- {c}" for c in (a.conditions if a else [])] or ["- (aucune : relire l'issue et les commentaires)"]
    lines += ["", "## Pile technique détectée", f"- stack : {', '.join(stack.get('stack', [])) or '?'}"]
    lines += [f"- installation : `{c}`" for c in stack.get("install", [])]
    lines += [f"- tests : `{c}`" for c in stack.get("test", [])]
    lines += [f"- lint : `{c}`" for c in stack.get("lint", [])]
    lines += [f"- note : {n}" for n in stack.get("notes", [])]
    lines += ["", "## Demande complète", "", b.body or "(corps vide : consulter l'issue en ligne)", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# -------------------------------------------------------------------- diff
def diff_summary(path: Path, base: str) -> dict[str, Any]:
    merge_base = git(["merge-base", f"origin/{base}", "HEAD"], path, check=False) or f"origin/{base}"
    stat = git(["diff", "--stat", f"{merge_base}..HEAD"], path, check=False)
    files = git(["diff", "--name-only", f"{merge_base}..HEAD"], path, check=False).splitlines()
    uncommitted = git(["status", "--porcelain"], path, check=False)
    commits = git(["log", "--oneline", f"{merge_base}..HEAD"], path, check=False).splitlines()
    return {"base": merge_base, "stat": stat, "files": files, "commits": commits,
            "uncommitted": bool(uncommitted.strip())}
