from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def write_repository(tmp_path: Path, *, branch: str) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    run_git(root, "init", "-b", "main")
    run_git(root, "config", "user.email", "test@example.invalid")
    run_git(root, "config", "user.name", "Test User")
    (root / "README.md").write_text("test\n", encoding="utf-8")
    run_git(root, "add", "README.md")
    run_git(root, "commit", "-m", "initial")
    run_git(root, "checkout", "-b", branch)

    template = (
        REPO_ROOT / "examples" / "project" / ".ollija" / "templates" / "delivery-guide.md"
    ).read_text(encoding="utf-8")
    template_path = root / ".ollija" / "templates" / "delivery-guide.md"
    template_path.parent.mkdir(parents=True)
    template_path.write_text(template, encoding="utf-8")
    contract = "\n".join(
        (
            "schema_version: 1",
            "authority:",
            "  canonical_host: test-host",
            f"  repository_root: {root}",
            "  repository_slug: example/test",
            "  release_worktree_label: Ollija release worktree area",
            "  release_worktree_path: .worktrees",
            "plans:",
            "  directory: docs/plans",
            "git:",
            "  remote: origin",
            "  staging_branch: staging",
            "  production_branch: main",
            "environments:",
            "  staging:",
            "    blueprint: deploy/staging.yaml",
            "    url: https://staging.example.invalid",
            "    service: staging",
            "  production:",
            "    blueprint: deploy/production.yaml",
            "    url: https://production.example.invalid",
            "    service: production",
            "delivery:",
            "  template: .ollija/templates/delivery-guide.md",
            "  test_commands: [python -m pytest]",
            "  code_failure_route: parent workflow",
            "  infra_failure_route: infrastructure workflow",
            "",
        )
    )
    (root / ".ollija" / "project.yaml").write_text(contract, encoding="utf-8")
    return root
