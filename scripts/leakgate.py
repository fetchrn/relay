#!/usr/bin/env python3
"""Independent leak-gate scanner for the Relay public repository.

Relay is a standalone, public, portfolio-grade project. It must never contain
the author's personal data, immigration/visa details, or any cross-contamination
from private sibling projects. This scanner runs in CI and as a pre-push hook;
it exits non-zero (failing the build / blocking the push) if anything banned
appears in a tracked file.

Design goals:
  * Deny-by-default for a curated set of distinctive banned terms.
  * Word-boundary matching so common English words never false-positive.
  * Generic secret detection (API keys, private-key headers, AWS keys).
  * Zero third-party dependencies — runs anywhere Python 3.11+ runs.

It is intentionally standalone (no relay package import) so it can be vendored
or run before the package is installable.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# --- Banned terms -----------------------------------------------------------
# Distinctive identifiers tied to the author or to private sibling projects.
# Chosen to be specific enough that they never collide with legitimate
# customer-support / agent vocabulary. Matched case-insensitively on word
# boundaries.
BANNED_TERMS: tuple[str, ...] = (
    # Author identity
    "dakshit",
    "unizel",
    # Private sibling projects that must not leak into this public repo
    "applybot",
    "job-automation",
    "sciren",
    "fetch-rn",
    "lifeos",
    "kairos",
    "hermes profile",
    # People named only in private context
    "vedanth",
    # Immigration / visa identifiers (never belong in a support-agent demo)
    "i-765",
    "i-907",
    "ioe9309928041",
    "z300221772",
)

# --- Regex patterns ---------------------------------------------------------
# Generic secret / PII shapes that should never be committed.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Stripe live secret key", re.compile(r"\bsk_live_[0-9a-zA-Z]{16,}\b")),
    ("Private key header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("US SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("USCIS A-number", re.compile(r"\bA\d{8,9}\b")),
)

# Files that are allowed to contain otherwise-banned tokens (this scanner
# itself names the banned terms, by necessity).
PATH_ALLOWLIST: frozenset[str] = frozenset(
    {
        "scripts/leakgate.py",
        "tests/test_leakgate.py",
    }
)

# Only scan text-like files; skip binaries and vendored trees.
SCANNED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".cfg",
        ".ini",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
        ".html",
        ".sh",
        ".env.example",
    }
)

SKIP_DIR_PARTS: frozenset[str] = frozenset(
    {".git", "node_modules", ".next", "out", ".venv", "venv", "__pycache__", "dist", "build"}
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    detail: str


def _banned_term_regexes() -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for term in BANNED_TERMS:
        # \b doesn't anchor around non-word edges (e.g. the hyphen in "i-765"),
        # so anchor on a lookaround that treats word chars as the boundary.
        pattern = re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", re.IGNORECASE)
        out.append((term, pattern))
    return out


def _tracked_files(root: Path) -> list[Path]:
    """Prefer git's tracked-file list; fall back to a filesystem walk."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        files = [root / line for line in result.stdout.splitlines() if line.strip()]
        if files:
            return files
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return [p for p in root.rglob("*") if p.is_file()]


def _should_scan(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIR_PARTS for part in rel.parts):
        return False
    if str(rel) in PATH_ALLOWLIST:
        return False
    # Match either a plain suffix or a compound like ".env.example".
    name = path.name
    if name in SCANNED_SUFFIXES:
        return True
    return path.suffix in SCANNED_SUFFIXES


def scan_text(rel_path: str, text: str) -> list[Finding]:
    """Scan one file's text. Pure function — unit-tested directly."""
    findings: list[Finding] = []
    term_regexes = _banned_term_regexes()
    for lineno, line in enumerate(text.splitlines(), start=1):
        for term, pattern in term_regexes:
            if pattern.search(line):
                findings.append(
                    Finding(rel_path, lineno, "banned-term", f"matched banned term {term!r}")
                )
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(rel_path, lineno, "secret", f"looks like {label}"))
    return findings


def scan_repo(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _tracked_files(root):
        if not path.is_file() or not _should_scan(path, root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(root))
        findings.extend(scan_text(rel, text))
    return findings


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else Path.cwd()
    findings = scan_repo(root)
    if not findings:
        print("leakgate: clean — no banned terms or secrets in tracked files.")
        return 0
    print(f"leakgate: FAILED — {len(findings)} finding(s):", file=sys.stderr)
    for f in findings:
        print(f"  {f.path}:{f.line}  [{f.kind}] {f.detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
