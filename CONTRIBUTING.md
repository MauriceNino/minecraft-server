# Contributing to MauriceNino/minecraft-server

## Quick Start

The project uses [uv](https://github.com/astral-sh/uv) for dependency management and project orchestration.

1.  **Fork and Clone** the repository.
2.  **Install dependencies** (the `dev` group is included by default):
    ```bash
    uv sync
    ```
3.  **Create a branch**:
    ```bash
    git checkout -b feat/your-feature-name
    # OR
    git checkout -b fix/your-bug-fix
    ```

## Development Workflow

CI runs all of the following, so run them before opening a PR.

### Linting and Formatting
We use [Ruff](https://github.com/astral-sh/ruff) for both linting and formatting.

- **Check for linting errors**:
  ```bash
  uv run ruff check .
  ```
- **Automatically fix linting errors and format code**:
  ```bash
  uv run ruff check --fix .
  uv run ruff format .
  ```

### Type Checking
We use [Pyright](https://github.com/microsoft/pyright) for static type checking.

- **Run type check**:
  ```bash
  uv run pyright
  ```

### Testing
We use [pytest](https://docs.pytest.org/) for our test suite.

- **Run all tests**:
  ```bash
  uv run pytest
  ```
- **Run specific tests**:
  ```bash
  uv run pytest tests/test_merger
  ```

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. The release notes are
generated from the commit messages, grouped by type.

### Format

`<type>(<scope>): <description>`, e.g. `feat(merger): add support for the !delete sigil in properties files`

### Types

- `feat`: A new feature (listed under Features)
- `fix`: A bug fix (Bug Fixes)
- `perf`: A performance improvement (Performance)
- `docs`: Documentation only changes (Documentation)
- `refactor`: A code change that neither fixes a bug nor adds a feature (Maintenance)
- `style`: Formatting and other changes that don't affect the meaning of the code (Maintenance)
- `test`: Adding missing tests or correcting existing tests (Maintenance)
- `build`: Changes to the Dockerfile, dependencies or packaging (Maintenance)
- `ci`: Changes to the GitHub Actions workflows and scripts (Maintenance)
- `chore`: Anything else that users don't notice, like tooling or contributor docs (Maintenance)

Commits with other types aren't listed in the release notes.

### Write for users

The commit messages become the release notes: every `feat`, `fix`, `perf` and `docs` subject is listed as it is, so write
it for someone who runs the image, not for a reviewer. Describe the feature or fix, not the code behind it, especially for
`feat` commits: `feat: add support for Pumpkin Market plugins` rather than `feat: add Pumpkin Market provider`. Keep it
a normal commit message, short and in the imperative.

### Breaking changes

Anything that can break an existing setup is a breaking change: a renamed or removed environment variable, a changed
default, a different volume layout or a dropped platform. Mark it with `!` after the type and add a `BREAKING CHANGE:`
footer that says what changed and what users have to do. The footer is shown under the commit in the release notes,
which list breaking changes first, and it calls for a major version.

```
feat(env)!: rename MEMORY to MAX_MEMORY

The old name was ambiguous next to the JVM's own flags.

BREAKING CHANGE: MEMORY is now MAX_MEMORY. Rename it in your compose file;
the old name is ignored and the server falls back to the default heap.
```

The body above the footer isn't part of the release notes.

## Releases (maintainers)

Releases follow [Semantic Versioning](https://semver.org) and are made by pushing a tag, nothing is released on its own.
The version comes from the tag (via `hatch-vcs`), so there is nothing to bump in the code. Tag the commit on `main` and
push the tag: `git tag v1.2.3 && git push origin v1.2.3`. Use a `-` suffix (`v1.3.0-rc.1`) for a prerelease, which gets
no `latest` tag and no shorter version tags.

The pipeline then builds every Java variant as `1.2.3-java<version>-<distribution>` (plus `1.2`, `1`, `latest` and the
moving `java<version>-<distribution>` tags) and creates a GitHub release with notes grouped from the commits since the
previous release. The docs site is only deployed for stable releases, so it always matches `latest`.

Every push to `main` is built as `edge` and `sha-<commit>` (Java 25 Temurin only), which never touches `latest`.

## Project Structure

- `src/orchestrator/`: Core Python source code.
  - `providers/`: Server JAR download per platform (Paper, Vanilla, etc.).
  - `plugins/`: Plugin resolution and download (Modrinth, Hangar, etc.).
  - `fs_orchestrator/`: Applying template directories to the runtime directory.
  - `merger/`: Sigil-aware config file merging.
  - `remote_access/`: RCON and management protocol config injection.
- `src/rcon/`: The `mc-rcon` client.
- `src/msmp/`: The `mc-msmp` client, with commands generated from the server's `rpc.discover` schema.
- `tests/`: Test suite using `pytest`.
- `examples/`: Docker Compose examples for different server types.
- `docs/`: Documentation site (built with Next.js/Fumadocs).

## Pull Request Process

1.  **Sync your fork**: Ensure your fork is up-to-date with the `main` branch.
2.  **Verify your changes**: Run linting, type checking, and tests before submitting.
3.  **Submit the PR**: Describe the change and link any related issues.
