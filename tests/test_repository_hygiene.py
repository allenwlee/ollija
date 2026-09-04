from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MODULES = {
    "__init__.py",
    "__main__.py",
    "annotate_plan.py",
    "cli.py",
    "config.py",
    "initialize.py",
    "worktrees.py",
}
RUNTIME_ASSETS = {
    "src/ollija/assets/agent-skills/ollija/SKILL.md",
    "src/ollija/assets/agent-skills/ollija/agents/openai.yaml",
    "src/ollija/assets/templates/plan-guide.md",
}
FORBIDDEN_IDENTITY_PARTS = (
    ("pushin", "weight"),
    ("fuchi", "talee"),
    ("on", "render"),
)
FORBIDDEN_IDENTITIES = tuple(
    re.compile(rf"{first}[\s_-]*{second}", re.IGNORECASE)
    for first, second in FORBIDDEN_IDENTITY_PARTS
)
FORBIDDEN_EMAIL_PARTS = (("allen", "quantma", "com"),)
FORBIDDEN_EMAILS = tuple(
    re.compile(rf"{local}@{domain}\.{suffix}", re.IGNORECASE)
    for local, domain, suffix in FORBIDDEN_EMAIL_PARTS
)
SOURCE_COMMIT = "".join(("62a", "50ad"))
ABSOLUTE_HOME = re.compile(r"/(?:Users|home)/[^/\s]+/")
REPOSITORY_REFERENCE = re.compile(
    r"github\.com/[^/\s]+/[^/\s]+/(?:commit|pull)/[^\s)]+",
    re.IGNORECASE,
)
DATABASE_URL = re.compile(
    r"(?:postgres(?:ql)?|mysql|mariadb)://(?P<user>[^\s/:@]+):(?P<password>[^\s@/]+)@",
    re.IGNORECASE,
)
TOKEN_PATTERNS = (
    re.compile(rf"(?<![A-Za-z0-9]){''.join(('s', 'k', '-'))}[A-Za-z0-9_-]{{20,}}"),
    re.compile(rf"(?<![A-Za-z0-9]){''.join(('g', 'h', 'p', '_'))}[A-Za-z0-9]{{20,}}"),
    re.compile(rf"(?<![A-Za-z0-9]){''.join(('github', '_pat_'))}[A-Za-z0-9_]{{20,}}"),
    re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])"),
)
PRIVATE_KEY_MARKER = "".join(("-----BEGIN ", "PRIVATE KEY-----"))
PLACEHOLDER_PASSWORDS = {
    "change-me",
    "changeme",
    "dummy",
    "example",
    "fake",
    "pass",
    "password",
    "placeholder",
    "secret",
    "test",
    "your_password",
}
FORBIDDEN_PATH_PARTS = {
    ".ollija/state",
    ".ollija/tmp",
    ".venv",
    ".worktrees",
    "__pycache__",
    "build",
    "dist",
}
FORBIDDEN_SUFFIXES = {".db", ".pyc", ".sqlite", ".sqlite3"}


def _git(*args: str, repo: Path = REPO_ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True)


def _git_bytes(*args: str, repo: Path) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo)


def _candidate_files() -> list[str]:
    output = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return sorted(path for path in output.split("\0") if path)


def scan_repository_history(repo: Path) -> list[str]:
    findings: list[str] = []
    for revision in _git("rev-list", "--all", repo=repo).splitlines():
        raw_metadata = _git_bytes(
            "show",
            "-s",
            "--format=%P%x00%an%x00%ae%x00%cn%x00%ce%x00%B",
            revision,
            repo=repo,
        ).decode("utf-8", errors="ignore")
        parents, author, author_email, committer, committer_email, message = raw_metadata.split(
            "\0", 5
        )
        if len(parents.split()) > 1:
            message = re.sub(
                r"\AMerge pull request #[0-9]+ from [^/\s]+/",
                "Merge pull request branch/",
                message,
                count=1,
            )
        findings.extend(f"commit message: {finding}" for finding in scan_text(message))
        identities = "\n".join((author, author_email, committer, committer_email))
        findings.extend(f"commit metadata: {finding}" for finding in scan_text(identities))

        paths = _git_bytes("ls-tree", "-r", "--name-only", "-z", revision, repo=repo)
        for encoded_path in paths.split(b"\0"):
            if not encoded_path:
                continue
            relative_path = encoded_path.decode("utf-8", errors="surrogateescape")
            findings.extend(
                f"{revision}:{relative_path}: {finding}" for finding in scan_path(relative_path)
            )
            findings.extend(
                f"{revision}:{relative_path}: path {finding}"
                for finding in scan_text(relative_path)
            )
            data = _git_bytes("cat-file", "blob", f"{revision}:{relative_path}", repo=repo)
            if b"\0" in data[:8192]:
                continue
            findings.extend(
                f"{revision}:{relative_path}: {finding}"
                for finding in scan_text(data.decode("utf-8", errors="ignore"))
            )
    return findings


def _is_placeholder(user: str, password: str) -> bool:
    lowered = password.lower()
    return (
        lowered in PLACEHOLDER_PASSWORDS
        or user == password
        or set(password) <= set("*xX-")
        or "<" in password
        or "{" in password
        or password.startswith("$")
    )


def scan_path(relative_path: str) -> list[str]:
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    findings: list[str] = []
    if any(
        forbidden == part or f"/{forbidden}/" in f"/{normalized}/"
        for forbidden in FORBIDDEN_PATH_PARTS
        for part in parts
    ):
        findings.append("runtime path")
    if Path(normalized).suffix.lower() in FORBIDDEN_SUFFIXES:
        findings.append("runtime suffix")
    if any(part.endswith(".egg-info") for part in parts):
        findings.append("package build metadata")
    return findings


def scan_text(text: str) -> list[str]:
    findings: list[str] = []
    if any(pattern.search(text) for pattern in FORBIDDEN_IDENTITIES):
        findings.append("private identity")
    if any(pattern.search(text) for pattern in FORBIDDEN_EMAILS):
        findings.append("private email")
    if SOURCE_COMMIT in text.lower():
        findings.append("source commit")
    if ABSOLUTE_HOME.search(text):
        findings.append("absolute home path")
    if REPOSITORY_REFERENCE.search(text):
        findings.append("repository-specific commit or pull request")
    if PRIVATE_KEY_MARKER in text or any(pattern.search(text) for pattern in TOKEN_PATTERNS):
        findings.append("credential-shaped value")
    for match in DATABASE_URL.finditer(text):
        if not _is_placeholder(match.group("user"), match.group("password")):
            findings.append("database credential")
            break
    return findings


def test_candidate_tree_has_no_identity_credentials_or_runtime_artifacts() -> None:
    findings: list[str] = []
    for relative_path in _candidate_files():
        findings.extend(f"{relative_path}: {finding}" for finding in scan_path(relative_path))
        findings.extend(f"{relative_path}: path {finding}" for finding in scan_text(relative_path))
        path = REPO_ROOT / relative_path
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        findings.extend(
            f"{relative_path}: {finding}"
            for finding in scan_text(data.decode("utf-8", errors="ignore"))
        )

    assert not findings, "repository hygiene findings:\n" + "\n".join(findings)


def test_complete_history_has_no_identity_credentials_or_runtime_artifacts() -> None:
    findings = scan_repository_history(REPO_ROOT)

    assert not findings, "repository history findings:\n" + "\n".join(findings)


def test_history_scanner_finds_deleted_content_and_commit_metadata(tmp_path: Path) -> None:
    repository = tmp_path / "history"
    subprocess.run(("git", "init", "-b", "main", str(repository)), check=True)
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.name", "Neutral User"), check=True
    )
    subprocess.run(
        ("git", "-C", str(repository), "config", "user.email", "neutral@example.invalid"),
        check=True,
    )
    note = repository / "private-note.txt"
    note.write_text("".join(("Pushin", "Weight")), encoding="utf-8")
    private_path = repository / ("".join(("Pushin", "Weight")) + ".txt")
    private_path.write_text("neutral\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", note.name, private_path.name), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=" + "".join(("Fuchi", "Talee")),
            "commit",
            "-m",
            "add note",
        ),
        check=True,
    )
    subprocess.run(("git", "-C", str(repository), "checkout", "-b", "side"), check=True)
    (repository / "side.txt").write_text("side\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "side.txt"), check=True)
    subprocess.run(("git", "-C", str(repository), "commit", "-m", "add side"), check=True)
    subprocess.run(("git", "-C", str(repository), "checkout", "main"), check=True)
    note.unlink()
    private_path.unlink()
    subprocess.run(("git", "-C", str(repository), "add", "--all"), check=True)
    subprocess.run(("git", "-C", str(repository), "commit", "-m", "remove note"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(repository),
            "-c",
            "user.email=" + "".join(("allen", "@", "quantma", ".com")),
            "merge",
            "--no-ff",
            "side",
            "-m",
            "merge side",
        ),
        check=True,
    )

    findings = scan_repository_history(repository)

    assert "commit metadata: private identity" in findings
    assert "commit metadata: private email" in findings
    assert any(finding.endswith("private-note.txt: private identity") for finding in findings)
    assert any(finding.endswith(".txt: path private identity") for finding in findings)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("".join(("Pushin", "Weight")), "private identity"),
        ("".join(("allen", "@", "quantma", ".com")), "private email"),
        ("/" + "Users/example/private/file", "absolute home path"),
        ("".join(("62a", "50ad")), "source commit"),
        (
            "https://github.com/example/project/" + "pull/42",
            "repository-specific commit or pull request",
        ),
        (
            "postgresql://" + "real-user:" + "nonplaceholder-value@database.invalid/app",
            "database credential",
        ),
        (
            "postgresql://" + "real-user:" + "abc@database.invalid/app",
            "database credential",
        ),
        ("".join(("s", "k", "-", "abcdefghijklmnopqrstuv")), "credential-shaped value"),
        ("".join(("-----BEGIN ", "PRIVATE KEY-----")), "credential-shaped value"),
    ],
)
def test_text_scanners_have_negative_fixtures(text: str, expected: str) -> None:
    assert expected in scan_text(text)


@pytest.mark.parametrize(
    "relative_path",
    [
        ".ollija/state/receipt.json",
        ".ollija/tmp/lock",
        "src/ollija/__pycache__/cli.pyc",
        "local.sqlite3",
        ".worktrees/feature/plan.md",
        "dist/ollija.whl",
    ],
)
def test_path_scanners_have_negative_fixtures(relative_path: str) -> None:
    assert scan_path(relative_path)


def test_runtime_package_is_the_retained_stateless_boundary() -> None:
    runtime = REPO_ROOT / "src" / "ollija"
    candidate_runtime_paths = {
        path for path in _candidate_files() if path.startswith("src/ollija/")
    }

    assert {path.name for path in runtime.glob("*.py")} == RUNTIME_MODULES
    assert candidate_runtime_paths == {
        *(f"src/ollija/{name}" for name in RUNTIME_MODULES),
        *RUNTIME_ASSETS,
    }


def test_runtime_artifacts_are_ignored() -> None:
    for relative_path in (
        ".ollija/state/example.json",
        ".ollija/tmp/annotation.lock",
        ".venv/bin/python",
        ".worktrees/example/plan.md",
        "build/lib/ollija.py",
        "dist/ollija.whl",
        "src/ollija/__pycache__/cli.pyc",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", relative_path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert ignored.returncode == 0, relative_path


def test_package_has_public_release_metadata() -> None:
    metadata = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"Private :: Do Not Upload"' not in metadata
    assert 'license = "0BSD"' in metadata
    assert "[project.urls]" in metadata
    assert 'Repository = "https://github.com/allenwlee/ollija"' in metadata


def test_ci_is_read_only_and_has_no_shipping_surface() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request", "push"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert set(workflow["jobs"]) == {"test", "build"}
    assert "Inspect distribution contents" in workflow_text
    assert '"annotate_plan.py"' in workflow_text
    assert "fetch-depth: 0" in workflow_text
    assert "secrets" not in workflow_text.lower()
    for forbidden in ("deploy", "publish", "release", "upload"):
        assert forbidden not in workflow_text.lower()

    uses = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", workflow_text, re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in uses)
