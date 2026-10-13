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

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. This helps in generating changelogs and managing versions automatically.

### Format
`<type>(<scope>): <description>`

### Types
- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code (white-space, formatting, etc)
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `perf`: A code change that improves performance
- `test`: Adding missing tests or correcting existing tests
- `chore`: Changes to the build process or auxiliary tools and libraries

### Example
`feat(merger): add support for !delete sigil in properties files`

## Project Structure

- `src/orchestrator/`: Core Python source code.
  - `providers/`: Server JAR download per platform (Paper, Vanilla, etc.).
  - `plugins/`: Plugin resolution and download (Modrinth, Hangar, etc.).
  - `fs_orchestrator/`: Applying template directories to the runtime directory.
  - `merger/`: Sigil-aware config file merging.
  - `rcon/`: RCON config injection.
- `src/rcon/`: The `mc-rcon` client.
- `tests/`: Test suite using `pytest`.
- `examples/`: Docker Compose examples for different server types.
- `docs/`: Documentation site (built with Next.js/Fumadocs).

## Pull Request Process

1.  **Sync your fork**: Ensure your fork is up-to-date with the `main` branch.
2.  **Verify your changes**: Run linting, type checking, and tests before submitting.
3.  **Submit the PR**: Describe the change and link any related issues.
