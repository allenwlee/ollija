# Contributing

Issues and pull requests are welcome.

## Development

Use Python 3.11 or newer on a POSIX system:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m build
```

Keep changes focused, include tests for behavior changes, and update documentation when a public
contract changes. By contributing, you agree that your contribution is licensed under the
repository's 0BSD license.
