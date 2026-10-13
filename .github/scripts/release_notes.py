#!/usr/bin/env python3
import os
import re
import subprocess
from datetime import datetime


def run_command(command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, shell=True)  # noqa: S602
    return result.stdout.strip()


def get_last_tag() -> str:
    return run_command("git describe --tags --abbrev=0 2>/dev/null")


def get_commits(since_tag: str | None = None) -> list[str]:
    range_str = f"{since_tag}..HEAD" if since_tag else ""

    output = run_command(f'git log {range_str} --pretty=format:"%s _by @%cn_ (%h)"')
    return output.splitlines() if output else []


def main() -> None:
    last_tag = get_last_tag()
    if last_tag:
        print(f"Comparing changes from {last_tag} to HEAD...")  # noqa: T201
    else:
        print("No previous tag found. Grabbing all commits from the beginning.")  # noqa: T201

    commits = get_commits(last_tag)
    print(f"Found {len(commits)} commits.")  # noqa: T201

    categories = {
        "feat": "🚀 Features",
        "fix": "🐛 Bug Fixes",
        "docs": "📚 Documentation",
        "maintenance": "🧹 Maintenance",
    }
    maintenance_types = {"chore", "refactor", "style", "test", "ci"}
    grouped: dict[str, list[str]] = {k: [] for k in categories}

    for commit in commits:
        # "type(scope): description" or "type: description"
        match = re.match(r"^(\w+)(?:\([^)]*\))?!?:\s*(.*)", commit)
        if not match:
            continue

        ctype, desc = match.groups()
        group = "maintenance" if ctype in maintenance_types else ctype
        if group in grouped:
            grouped[group].append(desc)

    # Compile the final Markdown release notes
    notes = []
    for key, title in categories.items():
        if grouped[key]:
            notes.append(f"### {title}")
            for item in grouped[key]:
                notes.append(f"- {item}")
            notes.append("")

    # Write notes to file
    with open("notes.txt", "w") as f:
        f.write("\n".join(notes).strip() + "\n")

    print("Generated Patchnotes Path: notes.txt")  # noqa: T201
    if notes:
        print("\n".join(notes))  # noqa: T201
    else:
        print("No grouped commits found.")  # noqa: T201

    # Generate the unique tag name (YYYY.M.D-shortsha)
    short_sha = run_command("git rev-parse --short HEAD")

    date_str = datetime.now().strftime("%Y.%-m.%-d")
    tag_name = f"{date_str}-{short_sha}"

    print(f"Generated Tag: {tag_name}")  # noqa: T201

    # Export variables for GitHub Actions
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"tag_name={tag_name}\n")


if __name__ == "__main__":
    main()
