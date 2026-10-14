"""Contrôle des textes publics avant livraison.

Règles appliquées au titre et au corps de la PR, à l'identité et au message de
chaque commit, et aux lignes ajoutées au dépôt cible :

- aucun tiret cadratin (U+2014) ni demi-cadratin (U+2013) ;
- aucun trailer de co-auteur ;
- aucun mot de la liste ``[publication] mots_interdits`` de la configuration,
  à déclarer dans ``bounty.local.toml`` (fichier non versionné).

Un mot écrit entièrement en majuscules est cherché en respectant la casse,
les autres sans en tenir compte. Les fichiers de données qui citent du contenu
tiers (correctifs exportés, verrous de dépendances) ne sont pas contrôlés.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .workspace import git

DASHES = {"\u2014": "tiret cadratin", "\u2013": "tiret demi-cadratin"}
TRAILER_RE = re.compile(r"^\s*co-authored-by\s*:", re.I)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")
EXEMPT_SUFFIXES = (".patch", ".diff", ".lock")
WORD_CHARS = "0-9A-Za-zÀ-ÖØ-öø-ÿ_"

Pattern = tuple[str, "re.Pattern[str]"]


@dataclass(frozen=True)
class Violation:
    where: str
    rule: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.where} : {self.rule} : {self.excerpt}"


def compile_words(words: Iterable[str]) -> list[Pattern]:
    patterns: list[Pattern] = []
    for word in words:
        word = word.strip()
        if not word:
            continue
        flags = 0 if word.isupper() else re.I
        rx = re.compile(rf"(?<![{WORD_CHARS}]){re.escape(word)}(?![{WORD_CHARS}])", flags)
        patterns.append((word, rx))
    return patterns


def check_line(line: str, where: str, patterns: list[Pattern]) -> list[Violation]:
    excerpt = line.strip()[:120]
    found: list[Violation] = []
    for char, name in DASHES.items():
        if char in line:
            found.append(Violation(where, name, excerpt))
    if TRAILER_RE.match(line):
        found.append(Violation(where, "trailer de co-auteur", excerpt))
    for word, rx in patterns:
        if rx.search(line):
            found.append(Violation(where, f"mot proscrit « {word} »", excerpt))
    return found


def check_text(text: str, where: str, words: Iterable[str] = ()) -> list[Violation]:
    patterns = compile_words(words)
    found: list[Violation] = []
    for number, line in enumerate((text or "").splitlines(), 1):
        found += check_line(line, f"{where}, ligne {number}", patterns)
    return found


def check_branch(path: Path, base_ref: str, words: Iterable[str] = ()) -> list[Violation]:
    """Contrôle les commits de ``base_ref..HEAD`` : identités, messages, lignes ajoutées."""
    patterns = compile_words(words)
    merge_base = git(["merge-base", base_ref, "HEAD"], path, check=False) or base_ref
    found: list[Violation] = []

    log = git(["log", "--format=%h%x1f%an <%ae>%x1f%cn <%ce>%x1f%B%x1e", f"{merge_base}..HEAD"],
              path, check=False)
    for record in log.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, author, committer, message = (record.split("\x1f") + ["", "", "", ""])[:4]
        found += check_line(author, f"auteur du commit {sha}", patterns)
        found += check_line(committer, f"committer du commit {sha}", patterns)
        for number, line in enumerate(message.splitlines(), 1):
            found += check_line(line, f"message du commit {sha}, ligne {number}", patterns)

    diff = git(["diff", "-U0", "--no-color", "--no-ext-diff", f"{merge_base}..HEAD"], path, check=False)
    current, exempt, in_header, lineno = "?", False, False, 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_header = True
            continue
        if in_header and not line.startswith("@@"):
            if line.startswith("+++ "):
                current = line[6:] if line.startswith("+++ b/") else line[4:]
                exempt = current.endswith(EXEMPT_SUFFIXES)
            continue
        in_header = False
        if line.startswith("@@"):
            match = HUNK_RE.match(line)
            lineno = int(match.group(1)) if match else 0
        elif line.startswith("+"):
            if not exempt:
                found += check_line(line[1:], f"{current}:{lineno}", patterns)
            lineno += 1
    return found
