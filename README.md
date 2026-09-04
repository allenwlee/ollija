# Ollija

Ollija is a small, deterministic command-line tool for keeping delivery guidance inside a
branch-matched Markdown plan. Developers and coding agents invoke the same command against the
same project-local contract and Git facts. Ollija (올리자) in Korean dev-speak means, "Let's deploy!"

Ollija is an early public alpha. It maintains planning guidance; it does not commit, push, deploy,
remove worktrees, or run a persistent service.

## Why Ollija?

- Developers and coding agents share one tracked project contract.
- Each named branch resolves to one Markdown plan.
- Generated guidance stays inside a replaceable marker-bounded block.
- Human-authored plan content and delivery exceptions remain untouched.
- A read-only check detects missing, malformed, ambiguous, cross-branch, or stale guidance before
  another workflow mutates the repository.

## Requirements

- Python 3.11 or newer
- Git
- A POSIX system

Windows is not currently supported because Ollija uses `fcntl` file locking, a shell hook, and Git
worktree conventions.

## Install

Install Ollija directly from GitHub as an isolated command:

```sh
uv tool install git+https://github.com/allenwlee/ollija.git
ollija --help
```

Upgrade an existing installation with:

```sh
uv tool upgrade ollija
```

## Quick start

Run initialization from a named branch in the repository that will use Ollija:

```sh
cd /path/to/project
ollija init --test-command "python -m pytest"
```

Initialization derives the repository host and slug from `origin`, then creates:

- `.ollija/project.yaml`, using the strict `plan-only` profile;
- `.ollija/templates/plan-guide.md`;
- `docs/plans`, unless another repository-relative location is selected; and
- the packaged neutral Ollija skill under `~/.agents/skills/ollija`.

The operation is idempotent. It does not overwrite an existing project contract, consumer-owned
skill, or conflicting template. Use `--no-install-agent-skill` if you want only the project files,
or `--skills-directory` to select another shared skill root.

Create or refresh the plan for the active branch:

```sh
ollija annotate-plan
```

The command prints structured JSON. Continue with the exact `plan_path` it returns rather than
creating another plan for the same branch. After editing the plan, refresh its generated guide:

```sh
ollija annotate-plan path/to/returned-plan.md
```

Before another workflow commits, pushes, or deploys, verify the guide without changing files:

```sh
ollija annotate-plan path/to/returned-plan.md --check
```

## Configuration

`docs/plans` is a default, not a hardcoded location. Configure another repository-relative
directory during initialization:

```sh
ollija init \
  --plans-directory plans \
  --test-command "python -m pytest" \
  --test-command "python -m ruff check ."
```

If `origin` does not expose a parseable HTTPS or SSH repository identity, pass both
`--canonical-host` and `--repository-slug`.

Keep `.ollija/project.yaml` and its template tracked so developers and agents use the same
contract. Plan-only contracts derive the repository root from their own location and remain valid
after a checkout is cloned or moved. Schema version 1 is strict at every mapping level.

### Delivery-profile compatibility

Existing version-one contracts without a `profile` field remain delivery contracts. They retain
their explicit staging and production branches, environments, worktree policy, test commands, and
failure routes. The complete contract under `examples/project/.ollija` is a reference for this
advanced profile; initialization deliberately does not invent deployment policy.

## Optional linked-worktree hook

The example hook annotates named linked worktrees without blocking checkout when Ollija is
unavailable or busy:

```sh
chmod +x .ollija/hooks/post-checkout
git config core.hooksPath .ollija/hooks
```

The hook invokes the installed `ollija` command. It skips primary and detached checkouts and
passes Git-derived paths only as quoted argument data.

## Trust and safety

Treat `.ollija/project.yaml`, its referenced template, and configured test commands as
repository-controlled executable guidance. Review changes to them with the same care as code
before following a generated plan.

Ollija safely loads YAML, constrains project-relative paths, quotes Git arguments in generated
delivery commands, uses exclusive creation for new plans, and replaces existing plans atomically.
The CLI itself does not execute configured test or delivery commands.

Report suspected vulnerabilities through GitHub's private vulnerability reporting rather than a
public issue. See [SECURITY.md](SECURITY.md) for the supported-version and response policy.

## Development

```sh
git clone https://github.com/allenwlee/ollija.git
cd ollija
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Ollija is released under the [0BSD license](LICENSE), which permits use, modification, and
distribution for any purpose without an attribution requirement.
