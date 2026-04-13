"""Mixed-scope commit audit CLI.

Scans git history or staged changes for commits that mix a plan/archive scope
with unrelated code files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
CODE_EXTENSIONS = {".py", ".ps1", ".svelte", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml", ".yml", ".yaml"}
HIGH_RISK_FILES = {
    "app/modules/dev_runner/services/event_service.py",
    "app/modules/dev_runner/services/executor_service.py",
    "app/routes/system.py",
}
IGNORED_DOC_MARKERS = {
    "fix-mixed-scope-commit-audit-and-dev-runner-sse-recovery",
    "mixed-scope-commit-audit",
    "index.md",
}

BACKTICK_RE = re.compile(r"`([^`]+)`")
LINK_RE = re.compile(r"\(([^)]+)\)")
FILELIKE_RE = re.compile(r"(?<![`(])[A-Za-z0-9_./\\-]+\.(?:py|ps1|svelte|ts|tsx|js|jsx|json|toml|yml|yaml|md)")
WORD_RE = re.compile(r"[A-Za-z0-9_]+")
STOP_TOKENS = {
    "add",
    "and",
    "archive",
    "change",
    "chore",
    "doc",
    "docs",
    "example",
    "feat",
    "feature",
    "fix",
    "implement",
    "issue",
    "mixed",
    "note",
    "plan",
    "refactor",
    "remove",
    "sample",
    "scope",
    "test",
    "todo",
    "update",
}


@dataclass(frozen=True)
class AuditFinding:
    sha: str
    subject: str
    linked_docs: tuple[str, ...]
    changed_files: tuple[str, ...]
    severity: str
    reason: str


def _run_git(args: list[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def _is_code_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    if normalized.startswith("docs/") or normalized.endswith(".md"):
        return False
    suffix = Path(normalized).suffix
    return suffix in CODE_EXTENSIONS


def _is_doc_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith("docs/") and normalized.endswith(".md")


def _is_ignored_doc_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(marker in normalized for marker in IGNORED_DOC_MARKERS)


def _normalize_token(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _tokenize(value: str) -> set[str]:
    normalized = _normalize_token(value)
    tokens: set[str] = set()
    for raw in re.split(r"[^a-z0-9_./-]+", normalized):
        raw = raw.strip("._-/")
        if len(raw) >= 3 and raw not in STOP_TOKENS:
            tokens.add(raw)
            for part in re.split(r"[._/-]+", raw):
                part = part.strip()
                if len(part) >= 3 and part not in STOP_TOKENS:
                    tokens.add(part)
    return tokens


def _extract_commit_tokens(subject: str, changed_files: Iterable[str]) -> tuple[set[str], set[str]]:
    subject_tokens = _tokenize(subject)
    file_tokens: set[str] = set()
    for changed_file in changed_files:
        normalized = _normalize_token(changed_file)
        file_tokens |= _tokenize(normalized)
        file_tokens.add(Path(normalized).name.lower())
        file_tokens.add(Path(normalized).stem.lower())
    subject_tokens.discard("staged")
    file_tokens.discard("staged")
    return subject_tokens, file_tokens


@lru_cache(maxsize=16)
def _load_repo_docs(repo_path: str) -> tuple[tuple[str, str], ...]:
    repo = Path(repo_path)
    docs: list[tuple[str, str]] = []
    for root in (repo / "docs" / "plan", repo / "docs" / "archive"):
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            rel = path.relative_to(repo).as_posix()
            if _is_ignored_doc_path(rel):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(encoding="utf-8", errors="ignore")
            docs.append((rel, content))
    return tuple(docs)


def _find_candidate_docs(repo: Path, subject_tokens: set[str], file_tokens: set[str]) -> list[Path]:
    candidates: list[Path] = []
    if not subject_tokens and not file_tokens:
        return candidates

    subject_list = sorted(subject_tokens, key=len, reverse=True)
    file_list = sorted(file_tokens, key=len, reverse=True)
    scored: list[tuple[int, Path]] = []
    for rel_path, text in _load_repo_docs(str(repo)):
        haystack = f"{rel_path}\n{text}".lower()
        score = 0
        for token in subject_list:
            if token in haystack:
                score += 2
        for token in file_list:
            if token in haystack:
                score += 1
        if score > 0:
            scored.append((score, repo / rel_path))

    if not scored:
        return candidates

    best_score = max(score for score, _ in scored)
    return [path for score, path in scored if score == best_score]


def _collect_plan_keywords(plan_path: Path) -> set[str]:
    if not plan_path.exists():
        return set()

    try:
        text = plan_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = plan_path.read_text(encoding="utf-8", errors="ignore")

    keywords: set[str] = set()
    for match in BACKTICK_RE.findall(text):
        keywords.add(_normalize_token(match))
    for match in LINK_RE.findall(text):
        normalized = _normalize_token(match)
        if "/" in normalized or "." in normalized:
            keywords.add(normalized)
    for match in FILELIKE_RE.findall(text):
        keywords.add(_normalize_token(match))

    for line in text.splitlines():
        if line.startswith("> ") or line.startswith("- ") or line.startswith("  - "):
            keywords |= _tokenize(line)

    keywords.add(_normalize_token(plan_path.name))
    keywords.add(_normalize_token(plan_path.stem))
    return {keyword for keyword in keywords if len(keyword) >= 3}


def _is_scope_mismatch(changed_file: str, keywords: set[str]) -> bool:
    normalized = _normalize_token(changed_file)
    if not _is_code_file(normalized):
        return False
    if not keywords:
        return True

    name = Path(normalized).name
    stem = Path(normalized).stem
    haystack = {
        normalized,
        name,
        stem,
        *(part for part in _tokenize(normalized)),
    }
    for keyword in keywords:
        if keyword in haystack:
            return False
        if keyword in normalized:
            return False
    return True


def _score_doc_for_file(doc_path: Path, doc_text: str, subject_tokens: set[str], file_tokens: set[str]) -> int:
    haystack = f"{doc_path.as_posix()}\n{doc_text}".lower()
    score = 0
    for token in subject_tokens:
        if token in haystack:
            score += 2
    for token in file_tokens:
        if token in haystack:
            score += 1
    return score


def _read_doc_text(repo: Path, doc_path: Path, sha: str | None = None) -> str:
    if sha is not None:
        rel_path = doc_path.relative_to(repo).as_posix()
        try:
            return _run_git(["show", f"{sha}:{rel_path}"], repo)
        except subprocess.CalledProcessError:
            pass

    try:
        return doc_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return doc_path.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return ""


def _file_scope_terms(path: str) -> set[str]:
    normalized = _normalize_token(path)
    p = Path(normalized)
    parts = [part for part in normalized.split("/") if part]
    terms = {normalized, p.name.lower(), p.stem.lower()}
    for width in range(2, min(len(parts), 5) + 1):
        terms.add("/".join(parts[-width:]))
    if len(parts) >= 3 and parts[0] in {"app", "tests", "frontend", "scripts"}:
        terms.add("/".join(parts[:3]))
    return {term for term in terms if len(term) >= 3}


def _code_domain(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 2:
        return normalized
    if parts[0] == "app" and len(parts) >= 3 and parts[1] == "modules":
        return "/".join(parts[:3])
    if parts[0] == "tests" and len(parts) >= 3 and parts[1] == "modules":
        return "/".join(parts[:3])
    if parts[0] == "frontend" and len(parts) >= 3:
        return "/".join(parts[:3])
    if parts[0] == "scripts" and len(parts) >= 2:
        return "/".join(parts[:2])
    return "/".join(parts[:2])


def _best_docs_for_file(
    candidate_docs: list[Path],
    subject_tokens: set[str],
    file_tokens: set[str],
    repo: Path | None = None,
    sha: str | None = None,
) -> list[Path]:
    scored: list[tuple[int, Path]] = []
    for doc_path in candidate_docs:
        if repo is not None:
            text = _read_doc_text(repo, doc_path, sha)
        else:
            try:
                text = doc_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = doc_path.read_text(encoding="utf-8", errors="ignore")
        score = _score_doc_for_file(doc_path, text, subject_tokens, file_tokens)
        if score > 0:
            scored.append((score, doc_path))

    if not scored:
        return []

    best_score = max(score for score, _ in scored)
    return [doc_path for score, doc_path in scored if score == best_score]


def _commit_subject(repo: Path, sha: str) -> str:
    return _run_git(["show", "-s", "--format=%s", sha], repo).strip()


def _get_changed_files(repo: Path, sha: str) -> list[str]:
    raw = _run_git(["show", "--pretty=format:", "--name-only", sha], repo)
    files = [line.strip() for line in raw.splitlines() if line.strip()]
    return files


def _get_staged_files(repo: Path) -> list[str]:
    raw = _run_git(["diff", "--cached", "--name-only"], repo)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _iter_candidate_commits(repo: Path, since: str | None, limit: int) -> list[str]:
    args = ["log", "--format=%H"]
    if since:
        args.extend(["--since", since])
    if limit > 0:
        args.extend(["-n", str(limit)])
    raw = _run_git(args, repo)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _severity_rank(value: str) -> int:
    order = {"P2": 0, "P1": 1, "P0": 2}
    return order.get(value, 0)


def _score_finding(subject: str, changed_files: list[str], mismatched_files: list[str]) -> str:
    lowered = subject.lower()
    if any(path in HIGH_RISK_FILES for path in mismatched_files):
        return "P0"
    if "test" in lowered and any(_is_code_file(path) and not path.startswith("tests/") for path in changed_files):
        return "P1"
    if len(mismatched_files) >= 2:
        return "P1"
    return "P2"


def _audit_commit(repo: Path, sha: str, subject: str, changed_files: list[str]) -> list[AuditFinding]:
    code_files = [path for path in changed_files if _is_code_file(path)]
    if not code_files:
        return []

    subject_tokens, file_tokens = _extract_commit_tokens(subject, changed_files)
    touched_docs = [repo / path for path in changed_files if _is_doc_file(path) and not _is_ignored_doc_path(path)]

    if touched_docs:
        file_to_docs: dict[str, list[Path]] = {}
        for file_path in code_files:
            file_terms = _file_scope_terms(file_path)
            file_to_docs[file_path] = _best_docs_for_file(touched_docs, set(), file_terms, repo=repo, sha=sha)

        uncovered_files = [path for path, docs in file_to_docs.items() if not docs]
        matched_doc_paths: list[str] = []
        for docs in file_to_docs.values():
            for doc_path in docs:
                rel = doc_path.relative_to(repo).as_posix()
                if rel not in matched_doc_paths:
                    matched_doc_paths.append(rel)

        domain_count = len({_code_domain(path) for path in code_files})
        if uncovered_files or len(matched_doc_paths) > 1 or domain_count >= 3:
            mismatched_files = uncovered_files or code_files
            severity = _score_finding(subject, code_files, mismatched_files)
            if len(mismatched_files) >= 3 and severity == "P2":
                severity = "P1"
            reason_bits = []
            if uncovered_files:
                reason_bits.append(f"{', '.join(uncovered_files[:3])} is not covered by the touched plan/archive scope")
            if len(matched_doc_paths) > 1:
                reason_bits.append(f"code files map to multiple touched docs: {', '.join(matched_doc_paths[:3])}")
            if domain_count >= 3:
                reason_bits.append(f"code files span {domain_count} distinct domains")
            reason = "; ".join(reason_bits)
            return [
                AuditFinding(
                    sha=sha,
                    subject=subject,
                    linked_docs=tuple(matched_doc_paths or [doc.relative_to(repo).as_posix() for doc in touched_docs]),
                    changed_files=tuple(changed_files),
                    severity=severity,
                    reason=reason,
                )
            ]
        return []

    candidate_docs = _find_candidate_docs(repo, subject_tokens, file_tokens)
    if not candidate_docs:
        return []

    file_to_docs: dict[str, list[Path]] = {}
    for file_path in code_files:
        file_terms = _file_scope_terms(file_path)
        best_docs = _best_docs_for_file(candidate_docs, set(), file_terms)
        file_to_docs[file_path] = best_docs

    unique_docs = []
    for docs in file_to_docs.values():
        for doc_path in docs:
            rel = doc_path.relative_to(repo).as_posix()
            if rel not in unique_docs:
                unique_docs.append(rel)

    if not unique_docs:
        if not candidate_docs:
            return []
        severity = _score_finding(subject, code_files, code_files)
        if len({_code_domain(path) for path in code_files}) >= 3 and severity == "P2":
            severity = "P1"
        reason = (
            f"{', '.join(code_files[:3])} is not covered by the candidate plan/archive scope "
            f"{', '.join(doc.relative_to(repo).as_posix() for doc in candidate_docs[:3])}"
        )
        return [
            AuditFinding(
                sha=sha,
                subject=subject,
                linked_docs=tuple(doc.relative_to(repo).as_posix() for doc in candidate_docs[:3]),
                changed_files=tuple(changed_files),
                severity=severity,
                reason=reason,
            )
        ]

    if len(unique_docs) == 1 and len({_code_domain(path) for path in code_files}) < 3:
        return []

    mismatched_files = [
        path
        for path, docs in file_to_docs.items()
        if not docs or len({doc.relative_to(repo).as_posix() for doc in docs}) == 0
    ]
    if not mismatched_files:
        mismatched_files = code_files

    severity = _score_finding(subject, code_files, mismatched_files)
    if len(unique_docs) > 1 and severity == "P2":
        severity = "P1"
    if len({_code_domain(path) for path in code_files}) >= 3 and severity == "P2":
        severity = "P1"

    reason = (
        f"{', '.join(mismatched_files[:3])} maps to a different plan/archive scope "
        f"than {', '.join(unique_docs[:3])}"
    )
    return [
        AuditFinding(
            sha=sha,
            subject=subject,
            linked_docs=tuple(unique_docs),
            changed_files=tuple(changed_files),
            severity=severity,
            reason=reason,
        )
    ]


def audit_repo(repo: Path, since: str | None = None, limit: int = 200, staged: bool = False) -> list[AuditFinding]:
    repo = repo.resolve()
    findings: list[AuditFinding] = []

    if staged:
        changed_files = _get_staged_files(repo)
        if not changed_files:
            return []
        subject = "[staged]"
        findings.extend(_audit_commit(repo, "STAGED", subject, changed_files))
        return findings

    for sha in _iter_candidate_commits(repo, since, limit):
        subject = _commit_subject(repo, sha)
        changed_files = _get_changed_files(repo, sha)
        findings.extend(_audit_commit(repo, sha, subject, changed_files))
    return findings


def _render_json(findings: list[AuditFinding]) -> str:
    payload = [asdict(finding) for finding in findings]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_markdown(findings: list[AuditFinding]) -> str:
    lines = [
        "# Mixed-Scope Commit Audit",
        "",
        "| Severity | SHA | Subject | Linked Docs | Changed Files | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for finding in findings:
        lines.append(
            "| "
            + " | ".join(
                [
                    finding.severity,
                    finding.sha,
                    finding.subject.replace("|", "\\|"),
                    "<br>".join(finding.linked_docs) or "-",
                    "<br>".join(finding.changed_files) or "-",
                    finding.reason.replace("|", "\\|"),
                ]
            )
            + " |"
        )
    if not findings:
        lines.append("| - | - | No findings | - | - | - |")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit mixed-scope commits")
    parser.add_argument("--repo", default=str(ROOT), help="Repository path to scan")
    parser.add_argument("--since", default=None, help="git log --since filter")
    parser.add_argument("--limit", type=int, default=200, help="Maximum number of commits to scan")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--staged", action="store_true", help="Inspect staged files instead of history")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    findings = audit_repo(repo, since=args.since, limit=args.limit, staged=args.staged)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.format == "json":
        print(_render_json(findings))
    else:
        print(_render_markdown(findings))

    if args.staged and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
