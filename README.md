# Ollija

Ollija is a small, deterministic command-line tool for keeping delivery guidance inside a
branch-matched Markdown plan. Developers and coding agents invoke the same command against the
same project-local contract and Git facts. Ollija (올리자) in Korean dev-speak means, "Let's deploy!"

Ollija is an early public alpha. It maintains planning guidance; it does not commit, push, deploy,
remove worktrees, or run a persistent service.

## Executive Summary

### Why it exists

Software teams increasingly combine human developers with coding agents, but the instructions that
govern a change are often scattered across chat, planning documents, branches, worktrees, and
deployment notes. That fragmentation creates practical ambiguity: two participants may choose
different plans, an agent may follow stale guidance, or a workflow may infer release authority that
the owner never granted.

Ollija creates one durable coordination point inside the repository. It binds each named Git branch
to one Markdown implementation plan, renders project-specific guidance into a clearly bounded part
of that plan, and verifies that the plan, branch, worktree, and tracked contract still agree before
another workflow changes the repository. Developers and coding agents invoke the same
Command-Line Interface (CLI: a program operated through typed shell commands), so neither side has
a separate or privileged source of instructions.

### Where it fits

Ollija is the plan-guidance layer between product intent and the systems that implement and deliver
software. It supplements planning tools, coding agents, Git, Continuous Integration (CI: automated
checks run against proposed changes), and deployment systems. It does not replace or operate any of
them.

The following American Standard Code for Information Interchange (ASCII) taxonomy shows that
placement:

```text
Software-delivery ecosystem
|
+-- Intent and planning
|   +-- Product requirements and owner decisions
|   +-- Architecture notes and implementation plans
|   `-- Explicit delivery scope and exceptions
|
+-- Ollija: deterministic plan-guidance layer
|   +-- Tracked project contract
|   +-- One named branch -> one Markdown plan
|   +-- Replaceable generated guidance
|   +-- Shared developer and coding-agent entry point
|   `-- Read-only freshness and consistency check
|
+-- Implementation workflow
|   +-- Developers and coding agents
|   +-- Source code and Git worktrees
|   `-- Project-owned tests and review
|
`-- Owner-controlled delivery
    +-- CI and staging
    +-- Merge and deployment
    `-- Monitoring, rollback, and worktree cleanup
```

The consuming repository owns the contract and plan. Ollija reads local Git facts, selects or
creates the branch-matched plan, and updates only its generated marker-bounded section. The parent
workflow remains responsible for implementation, tests, commits, pushes, deployment, and any
guarded cleanup.

### Brief history and evolution

Ollija began as a project-specific delivery-plan annotator within a larger application repository.
An earlier stateful release engine was retired, leaving a smaller stateless core focused on plan
selection, deterministic guidance, and pre-mutation checks. That core was then extracted into a
standalone Python package with neutral project assets, clean repository history, and no dependency
on the original application's services or data.

The first public release added project initialization and a portable agent skill. New adopters can
now create a strict plan-only contract with `ollija init`; existing advanced delivery contracts
remain supported without making deployment policy a default.

### What it replaces and what it supplements

Ollija replaces:

- ad hoc branch-to-plan lookup performed independently by each person or agent;
- duplicated or competing implementation plans for the same branch;
- hand-maintained instruction blocks that silently drift from project configuration;
- informal checks for whether guidance still matches the active branch and worktree; and
- the assumption that an agent-specific prompt should carry hidden release authority.

Ollija supplements:

- product and engineering plans by keeping generated execution guidance beside human intent;
- coding-agent skills by giving different agent systems one deterministic command and contract;
- Git branches and linked worktrees by making their relationship to a plan explicit;
- CI and review by providing a read-only check before mutations begin; and
- deployment workflows by recording owner-selected targets and guarded instructions without
  executing them.

### Strategic value

For an engineering organization, Ollija is a small interoperability layer for human-and-agent
delivery. It reduces coordination errors without introducing a hosted control plane, proprietary
agent runtime, database, or background service. Because its contract is tracked with the code and
its output is deterministic, teams can review changes to delivery guidance through ordinary source
control and reproduce the same result across machines and agent products.

The immediate value is fewer stale-plan, wrong-branch, and accidental-authority mistakes. The
longer-term value is a common planning boundary across a portfolio of repositories: each product
can retain its own stack and delivery process while exposing the same small, auditable interface to
developers and coding agents.

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
