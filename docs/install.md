# Install

## From PyPI

```bash
pip install fantasyfb
```

Python 3.10, 3.11, or 3.12 is required. The install pulls in pandas,
numpy, pyarrow, openpyxl, plus the Yahoo Fantasy API client and
`nflreadpy` for projection data.

## From source

```bash
git clone https://github.com/tefirman/fantasyfb.git
cd fantasyfb
pip install -e ".[dev]"
```

The `[dev]` extra adds `pytest`, `ruff`, and `build`.

To work on the docs site itself:

```bash
pip install -e ".[docs]"
mkdocs serve     # local preview at http://127.0.0.1:8000
mkdocs build     # produces ./site/
```

## After install

Before you can do anything useful you need:

1. **Yahoo OAuth credentials** — see [Yahoo OAuth setup](yahoo-oauth.md).
2. **A Yahoo fantasy team** the credentials have access to.

Once both are in place, the [quickstart](quickstart.md) walks you
through your first weekly report.
