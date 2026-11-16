#!/usr/bin/env python3
"""Write the release notes for a `vMAJOR.MINOR.PATCH` tag to `notes.md`.

Usage: release_notes.py <tag>

The notes list the Conventional Commits between the previous release and <tag>, grouped by type. Fails if the tag
isn't a SemVer tag.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$")
COMMIT = re.compile(r"^(\w+)(?:\([^)]*\))?(!)?:\s*(.*)")
# A `BREAKING CHANGE:` footer runs until the next footer (`Token: value` or `Token #123`) or the end of the message
BREAKING_FOOTER = re.compile(
    r"^BREAKING[ -]CHANGE:[ \t]*(.*?)(?=^[A-Za-z][A-Za-z-]*(?:: | #)|\Z)", re.MULTILINE | re.DOTALL
)

BREAKING = "⚠️ Breaking Changes"
CATEGORIES = {
    BREAKING: set(),
    "🚀 Features": {"feat"},
    "🐛 Bug Fixes": {"fix"},
    "⚡ Performance": {"perf"},
    "📚 Documentation": {"docs"},
    "🧹 Maintenance": {"chore", "refactor", "style", "test", "ci", "build"},
}


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    return result.stdout.strip()


def previous_tag(tag: str) -> str:
    """The release before `tag`: the previous stable one for a stable release, any previous one for a prerelease."""
    prerelease = "-" in tag
    # Newest first, with `versionsort.suffix` making `v1.0.0-rc.1` sort before `v1.0.0`
    tags = git("-c", "versionsort.suffix=-", "tag", "--list", "v*", "--sort=-version:refname").splitlines()
    releases = [t for t in tags if SEMVER_TAG.match(t) and (prerelease or "-" not in t)]
    if tag in releases and releases.index(tag) + 1 < len(releases):
        return releases[releases.index(tag) + 1]
    # The first release: continue from the last tag of the old date-based scheme, skipping prereleases
    return git("describe", "--tags", "--abbrev=0", "--exclude", "v*-*", f"{tag}^")


def github_logins(repository: str | None, previous: str, tag: str) -> dict[str, str]:
    """GitHub usernames of the commit authors by short SHA, empty without `gh` or a GitHub repository."""
    if not (repository and previous):
        return {}
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "gh",
            "api",
            "--paginate",
            f"repos/{repository}/compare/{previous}...{tag}?per_page=100",
            "--jq",
            '.commits[] | [.sha, (.author.login // "")] | @tsv',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Couldn't look up GitHub usernames, using the Git author names: {result.stderr.strip()}")  # noqa: T201
        return {}
    logins = (line.split("\t") for line in result.stdout.splitlines() if "\t" in line)
    return {sha: login for sha, login in logins if login}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tag = sys.argv[1]

    if not SEMVER_TAG.match(tag):
        sys.exit(f"{tag} is not a SemVer tag (expected vMAJOR.MINOR.PATCH, optionally with a -prerelease suffix)")

    previous = previous_tag(tag)
    print(f"Collecting changes from {previous or 'the beginning'} to {tag}...")  # noqa: T201
    repository = os.environ.get("GITHUB_REPOSITORY")
    logins = github_logins(repository, previous, tag)

    log = git(
        "log", f"{previous}..{tag}" if previous else tag, "--no-merges", "--pretty=format:%s%x1f%b%x1f%an%x1f%H%x1e"
    )
    grouped: dict[str, list[str]] = {title: [] for title in CATEGORIES}

    for entry in filter(None, (e.strip() for e in log.split("\x1e"))):
        subject, body, author, sha = entry.split("\x1f")
        match = COMMIT.match(subject)
        if not match:
            continue

        ctype, bang, description = match.groups()
        # A GitHub username becomes a mention, an author without a linked account keeps their Git name
        by = f"@{logins[sha]}" if sha in logins else author
        line = f"{description[:1].upper()}{description[1:]} _by {by}_ ({sha[:7]})"
        footer = BREAKING_FOOTER.search(body)
        if bang or footer:
            # What users have to do goes under the entry, indented to stay part of the list item
            details = footer.group(1).strip() if footer else ""
            grouped[BREAKING].append(line + "".join(f"\n  {text}" for text in details.splitlines()))
            continue
        for title, types in CATEGORIES.items():
            if ctype in types:
                grouped[title].append(line)
                break

    notes: list[str] = []
    for title, items in grouped.items():
        if items:
            notes += [f"### {title}", *(f"- {item}" for item in items), ""]

    if previous and repository:
        notes.append(f"**Full changelog**: https://github.com/{repository}/compare/{previous}...{tag}")

    text = "\n".join(notes).strip() or "No notable changes."
    Path("notes.md").write_text(text + "\n")
    print(f"Wrote notes.md:\n\n{text}")  # noqa: T201


if __name__ == "__main__":
    main()
