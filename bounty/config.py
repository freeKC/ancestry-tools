"""Chargement de la configuration (``bounty.toml``) avec valeurs par défaut."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

try:  # Python >= 3.11
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - dépend de l'interpréteur
    try:
        import toml as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _toml = None  # type: ignore[assignment]

DEFAULTS: dict[str, Any] = {
    "profil": {
        # Langages dans lesquels on accepte de travailler (langage principal du dépôt).
        "langages": ["Python", "TypeScript", "JavaScript"],
        "github_login": "",
        "montant_min": 20,
        "montant_max": 5000,
        # Au-delà, la prime est probablement bloquée ou déjà traitée.
        "age_max_jours": 120,
        # Nombre de /attempt ou /claim déjà postés par d'autres au-delà duquel on passe.
        "claims_max": 2,
        # Nombre de PR ouvertes concurrentes toléré.
        "prs_ouvertes_max": 1,
        # Identité git appliquée aux clones de travail par `start` (vide : identité globale).
        "git_nom": "",
        "git_email": "",
    },
    "sources": {
        "github_labels": ["💎 Bounty", "bounty", "💰 Bounty", "Bounty"],
        "recherche_jours": 90,
        "pages_max": 3,
        # Dépôts pièges ou de test : volumes énormes d'« issues » à prime, jamais payées.
        "exclure_proprietaires": [
            "SecureBananaLabs",
            "UnsafeLabs",
            "WillSmithTE",
            "ApexOpsStudio",
            "habibdxb01",
        ],
        # Fragments de labels (comparaison sans casse, par inclusion).
        "exclure_labels": ["no humans", "on-hold", "rewarded", "wontfix"],
        # Mots dans le titre ou le corps qui signalent une tâche non logicielle ou un piège.
        "exclure_mots": ["needs-game", "payout wallet", "no humans"],
        "algora_api": "https://console.algora.io/api/trpc/bounty.list",
    },
    "workspace": {
        "dossier": ".bounty/work",
        "etat": ".bounty/state.json",
        "dossiers": ".bounty/dossiers",
        "timeout_tests_s": 1800,
    },
    "github": {
        "token_env": "GITHUB_TOKEN",
        "api": "https://api.github.com",
    },
    "livraison": {
        # Syntaxe de réclamation par plateforme : {n} = numéro de l'issue.
        "claim": {"algora": "/claim #{n}", "opire": "/opire claim #{n}"},
        "signature": "",
    },
    "publication": {
        # Mots à proscrire dans tout texte public (PR, commits, lignes ajoutées).
        # À déclarer dans bounty.local.toml, fichier non versionné.
        "mots_interdits": [],
    },
}

LOCAL_NAME = "bounty.local.toml"


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if _toml is None:
        raise RuntimeError("Lecture TOML impossible : installez Python >= 3.11 ou le paquet 'toml'.")
    return _toml.loads(path.read_text(encoding="utf-8"))


def find_config(start: Path | None = None) -> Path | None:
    """Remonte l'arborescence à la recherche de ``bounty.toml``."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        path = candidate / "bounty.toml"
        if path.is_file():
            return path
    return None


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else find_config()
    data: dict[str, Any] = {}
    if cfg_path and cfg_path.is_file():
        data = _read_toml(cfg_path)
        # Réglages personnels non versionnés (identité git, mots proscrits) : priorité au local.
        local = cfg_path.with_name(LOCAL_NAME)
        if local.is_file():
            data = _merge(data, _read_toml(local))
    cfg = _merge(DEFAULTS, data)
    cfg["_path"] = str(cfg_path) if cfg_path else None
    root = cfg_path.parent if cfg_path else Path.cwd()
    cfg["_root"] = str(root)
    return cfg


def github_token(cfg: dict[str, Any]) -> str | None:
    env_name = cfg.get("github", {}).get("token_env", "GITHUB_TOKEN")
    return os.environ.get(env_name) or os.environ.get("GH_TOKEN") or None


def resolve(cfg: dict[str, Any], relative: str) -> Path:
    """Chemin absolu relatif à la racine du projet (dossier de ``bounty.toml``)."""
    return Path(cfg["_root"]) / relative
