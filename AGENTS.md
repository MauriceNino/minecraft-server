# AGENTS.md

Setup, checks and the project layout are in [CONTRIBUTING.md](CONTRIBUTING.md). Before committing, run
`uv run ruff format .`, `uv run ruff check .`, `uv run pyright` and `uv run pytest`, and for docs changes
`npm run test` in `docs/`.

## Pumpkin

Pumpkin is very experimental, and most users don't run it. Keep everything about it on its own pages,
`docs/content/docs/platforms/pumpkin.mdx` and `docs/content/docs/plugins/pumpkin.mdx`, including its edge cases and
exceptions to general behavior. Other pages only mention it where every platform, provider or environment variable is
listed (navigation, the platform overview table, `environment.mdx`).

## Docs

- Change the docs in the same commit as the code they describe, not in a separate docs commit.
- American English (`color`, not `colour`).
- Hints and warnings are Fumadocs `<Callout>` components, not GitHub-style `> [!TIP]` blocks, which render as raw
  text.
- Markdown is wrapped at 120 characters by oxfmt: run `npx oxfmt` in `docs/` on the files you touched.

## Examples

Keep each example under `examples/` small and focused on one setup. Add a new example rather than growing an existing
one. Don't set `container_name` in Compose files.
