<!--
SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>

SPDX-License-Identifier: BSL-1.0
-->

# cppa-weblate-plugin

## Development

This repository uses [uv](https://docs.astral.sh/uv/) for environments and [prek](https://pypi.org/project/prek/) (a Rust hook manager that reads `.pre-commit-config.yaml`) to run the same hooks as CI locally.

Install dependencies including the hook runner:

```bash
uv sync --group pre-commit
```

Run every hook on the whole tree:

```bash
uv run --only-group pre-commit prek run --all-files --show-diff-on-failure
```

Install Git commit hooks so hooks run on each commit:

```bash
uv run --only-group pre-commit prek install
```

If you use the classic `pre-commit` CLI instead of prek, install it separately and run `pre-commit install` after `uv sync`.

## License

This plugin is BSL-licensed; when used with Weblate, Weblate's GPLv3 license applies to the combined deployment. See `LICENSE` for the Boost Software License text.
