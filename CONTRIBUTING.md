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
| GitHub repository | `tai-<name>` |

So a dependency is declared as `tai42-<name>` while its repository is named
`tai-<name>`, and both spellings are correct in their own context.

Some surfaces are deliberately neither, and must not be renamed: the `tai` CLI
command (`tai42` is an alias), the Prometheus metric namespace (`tai_tool_*`),
`TAI_*` environment variables, and the `tai-plugin.yml` descriptor filename.

## Dev

```bash
uv venv --python 3.13
uv pip install --no-sources --group dev --editable .
uv run --no-sync pytest --cov --cov-report=term-missing
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pyright
```

`make dev` installs the sibling `tai-contract` and `tai-kit` repos as editable installs for local cross-repo development.

Before any commit, run a secret scan over `src/` and `tests/` (e.g.
`detect-secrets scan`).

## Dependency resolution

`uv.lock` pins the `tai42-*` siblings to their released index versions while `[tool.uv.sources]` points them at local `../tai-*` checkouts. The two disagree deliberately: CI sets `UV_NO_SOURCES=1` and asserts the lock with `uv sync --locked`, so it resolves the artifacts a user installs. A bare `uv lock` beside sibling checkouts re-couples the lock to editable path entries, which then fails that `--locked` check — run `uv lock --no-sources` instead. See [How dependencies resolve](https://tai42.ai/contributing#how-dependencies-resolve).

## License

By contributing you agree your contributions are licensed under Apache-2.0.
