"""Modèles de données du pipeline (prime, analyse, élément de pipeline)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any

ISSUE_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)"
    r"/issues/(?P<number>\d+)"
)
KEY_RE = re.compile(r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)#(?P<number>\d+)$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Stage(str, Enum):
    RECHERCHE = "recherche"
    RESOLUTION = "resolution"
    VERIFICATION = "verification"
    LIVRAISON = "livraison"
    PAIEMENT = "paiement"
    TERMINE = "termine"
    ABANDONNE = "abandonne"


STAGE_ORDER = [
    Stage.RECHERCHE,
    Stage.RESOLUTION,
    Stage.VERIFICATION,
    Stage.LIVRAISON,
    Stage.PAIEMENT,
    Stage.TERMINE,
]

# Travail automatisé et intervention attendue de l'utilisateur, par étape.
PIPELINE_WORK = {
    Stage.RECHERCHE: "Repérer les primes et analyser les demandes",
    Stage.RESOLUTION: "Lire le code, reproduire le problème, programmer",
    Stage.VERIFICATION: "Exécuter les tests et examiner les changements",
    Stage.LIVRAISON: "Préparer la proposition et son explication",
    Stage.PAIEMENT: "Suivre le statut",
}
CHECKPOINTS = {
    Stage.RECHERCHE: "Choisir une tâche et vérifier ses conditions",
    Stage.RESOLUTION: "Arbitrer les points ambigus",
    Stage.VERIFICATION: "Vérifier que le résultat répond à la demande",
    Stage.LIVRAISON: "Valider la soumission",
    Stage.PAIEMENT: "Recevoir le paiement sur son compte",
}


def parse_ref(text: str) -> tuple[str, str, int]:
    """Accepte une URL d'issue GitHub ou une clé ``owner/repo#123``."""
    text = text.strip()
    m = ISSUE_URL_RE.search(text) or KEY_RE.match(text)
    if not m:
        raise ValueError(f"Référence d'issue non reconnue : {text!r}")
    return m.group("owner"), m.group("repo"), int(m.group("number"))


def _filter_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


@dataclass
class Bounty:
    owner: str
    repo: str
    number: int
    title: str = ""
    amount_usd: float | None = None
    platform: str = "inconnu"  # algora | opire | polar | label | inconnu
    labels: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    language: str | None = None
    state: str = "open"
    assignees: list[str] = field(default_factory=list)
    comments_count: int = 0
    body: str = ""
    source: str = ""
    discovered_at: str = field(default_factory=now_iso)
    prescore: float | None = None
    prescore_notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/issues/{self.number}"

    @property
    def repo_full(self) -> str:
        return f"{self.owner}/{self.repo}"

    @classmethod
    def from_ref(cls, ref: str, **kwargs: Any) -> "Bounty":
        owner, repo, number = parse_ref(ref)
        return cls(owner=owner, repo=repo, number=number, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        d["url"] = self.url
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Bounty":
        return cls(**_filter_kwargs(cls, data))


@dataclass
class Analysis:
    score: float = 0.0
    verdict: str = "NON"  # GO | PRUDENCE | NON
    reasons: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    amount_usd: float | None = None
    claims: int = 0
    claimants: list[str] = field(default_factory=list)
    linked_prs_open: int = 0
    linked_prs_merged: int = 0
    linked_prs_closed: int = 0
    age_days: float | None = None
    repo_stars: int | None = None
    repo_is_fork: bool = False
    repo_archived: bool = False
    repo_language: str | None = None
    repo_pushed_at: str | None = None
    repo_rewarded_before: int | None = None
    bot_bounty_comment: bool = False
    tests_present: bool | None = None
    spec_quality: int = 0  # 0..10
    assigned: bool = False
    conditions: list[str] = field(default_factory=list)
    analyzed_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Analysis":
        return cls(**_filter_kwargs(cls, data))


@dataclass
class VerifyResult:
    command: str
    returncode: int
    duration_s: float
    output_tail: str
    ran_at: str = field(default_factory=now_iso)

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerifyResult":
        return cls(**_filter_kwargs(cls, data))


@dataclass
class PipelineItem:
    bounty: Bounty
    stage: Stage = Stage.RECHERCHE
    analysis: Analysis | None = None
    workspace: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    stack: dict[str, Any] = field(default_factory=dict)
    verify_results: list[VerifyResult] = field(default_factory=list)
    pr_url: str | None = None
    pr_number: int | None = None
    pr_state: str | None = None  # open | merged | closed
    paid: bool = False
    paid_note: str | None = None
    notes: list[str] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def key(self) -> str:
        return self.bounty.key

    @property
    def checkpoint(self) -> str | None:
        """Intervention de l'utilisateur attendue pour l'étape courante."""
        return CHECKPOINTS.get(self.stage)

    def log(self, note: str, stage: Stage | None = None) -> None:
        if stage is not None:
            self.stage = stage
        self.updated_at = now_iso()
        self.history.append({"at": self.updated_at, "stage": self.stage.value, "note": note})

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounty": self.bounty.to_dict(),
            "stage": self.stage.value,
            "checkpoint": self.checkpoint,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "workspace": self.workspace,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "stack": self.stack,
            "verify_results": [v.to_dict() for v in self.verify_results],
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "pr_state": self.pr_state,
            "paid": self.paid,
            "paid_note": self.paid_note,
            "notes": self.notes,
            "history": self.history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineItem":
        item = cls(bounty=Bounty.from_dict(data["bounty"]))
        item.stage = Stage(data.get("stage", Stage.RECHERCHE.value))
        if data.get("analysis"):
            item.analysis = Analysis.from_dict(data["analysis"])
        item.workspace = data.get("workspace")
        item.branch = data.get("branch")
        item.base_branch = data.get("base_branch")
        item.stack = data.get("stack") or {}
        item.verify_results = [VerifyResult.from_dict(v) for v in data.get("verify_results", [])]
        item.pr_url = data.get("pr_url")
        item.pr_number = data.get("pr_number")
        item.pr_state = data.get("pr_state")
        item.paid = bool(data.get("paid", False))
        item.paid_note = data.get("paid_note")
        item.notes = list(data.get("notes", []))
        item.history = list(data.get("history", []))
        item.created_at = data.get("created_at", item.created_at)
        item.updated_at = data.get("updated_at", item.updated_at)
        return item
