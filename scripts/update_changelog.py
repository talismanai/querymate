#!/usr/bin/env python3
import sys
from datetime import datetime
from pathlib import Path


def update_changelog(version: str, changelog_entry: str, release_type: str) -> None:
    """Update the CHANGELOG.md file with the new version and changelog entry."""
    changelog_path = Path("CHANGELOG.md")

    # Create CHANGELOG.md if it doesn't exist
    if not changelog_path.exists():
        with open(changelog_path, "w") as f:
            f.write("# Changelog\n\n")

    # Read current content
    with open(changelog_path) as f:
        content = f.read()

    # Prepare new changelog entry
    today = datetime.now().strftime("%Y-%m-%d")
    new_entry = f"""## [{version}] - {today}

### {release_type.capitalize()} Changes

{changelog_entry}

"""

    # Insert new entry after the title
    if content.startswith("# Changelog\n\n"):
        new_content = content.replace("# Changelog\n\n", f"# Changelog\n\n{new_entry}")
    else:
        new_content = f"# Changelog\n\n{new_entry}{content}"

    # Write back to file
    with open(changelog_path, "w") as f:
        f.write(new_content)

    print(f"Updated CHANGELOG.md with version {version}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python update_changelog.py <version> <changelog_entry> <release_type>"
        )
        sys.exit(1)

    version = sys.argv[1]
    changelog_entry = sys.argv[2]
    release_type = sys.argv[3]

    if release_type not in ["major", "minor", "patch"]:
        print("Error: release_type must be one of: major, minor, patch")
        sys.exit(1)

    update_changelog(version, changelog_entry, release_type)
