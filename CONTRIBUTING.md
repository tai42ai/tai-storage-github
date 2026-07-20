# Contributing to tai42-storage-github

`tai42-storage-github` is the GitHub-backed **Storage** provider for the TAI
ecosystem: it stores content as files in a GitHub repository and serves the full
`tai42_contract.storage.Storage` surface — the text methods (`load` / `list` /
`upload` / `delete` / `delete_dir`) plus the binary/media methods (`load_bytes` /
`upload_bytes` / `stat`). The hard rule (the plugin rule): **it depends on
`tai42-contract` + `tai42-kit` only and never imports the skeleton.** Importing the
`tai42_storage_github` package fires the `@tai42_app.storage.register_storage`
decorator on `GithubStorage` as a side-effect, so naming the package in a
manifest's `storage_module` activates it — there is no import edge to the
skeleton in either direction.

## Ground rules

- **No skeleton import — ever.** The package is contract-facing; the ban is
  enforced by ruff (`flake8-tidy-imports`), so a stray import fails lint:
  ```bash
  grep -rn "tai42_skeleton" src/   # must be empty
  ```
- **Loud errors.** No swallowed exceptions, silent fallbacks, or silent
  truncation. An oversized write, a `truncated` tree listing, or a failed
  request raises rather than acting on partial data.
- **The token stays secret.** It is held as a `SecretStr` and never appears in a
  log line, repr, or error message.
- **Typed package** (`py.typed`). Pyright runs clean.

## Layout

- `storage.py` — `GithubStorage` (the `Storage` impl) and its registration.
- `client.py` — the pooled GitHub HTTP client (raw endpoint for reads, Contents
  API for writes, Git Trees API for listing).
- `settings.py` — the `STORAGE_GITHUB_` settings.

## Naming

PyPI is a flat namespace with no owner in the path, so distributions carry the
`tai42-` prefix. GitHub repositories keep their `tai-` names, because the
`tai42ai` organisation already namespaces them. Import packages follow the
distribution.

| Surface | Form |
| --- | --- |
| Distribution — PyPI, `pip install`, dependency pins | `tai42-<name>` |
| Import package | `tai42_<name>` |
| GitHub repository and sibling checkout directory | `tai-<name>` |

So a dependency is declared as `tai42-<name>` but resolved from `../tai-<name>`
during local development, and both spellings are correct in their own context.

Some surfaces are deliberately neither, and must not be renamed: the `tai` CLI
command (`tai42` is an alias), the Prometheus metric namespace (`tai_tool_*`),
`TAI_*` environment variables, and the `tai-plugin.yml` descriptor filename.

## Dev

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

For local cross-repo work, `make dev` editable-installs the sibling `tai-*`
checkouts this package builds on into the venv. While `[tool.uv.sources]` pins
those siblings to local paths, `uv sync` already installs them editable and
`make dev` changes nothing; once the lock resolves them from the registry,
`uv sync` / `uv run` installs the published builds instead, so re-run
`make dev` afterward to restore the editable links.

Before any commit, run a secret scan over `src/` and `tests/` (e.g.
`detect-secrets scan`).

## License

By contributing you agree your contributions are licensed under Apache-2.0.
