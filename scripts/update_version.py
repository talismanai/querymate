#!/usr/bin/env python3
import sys
from pathlib import Path

import toml


def update_version(new_version: str) -> None:
    """Update the version in pyproject.toml and __init__.py."""
    # Update pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found")

    # Read and parse the file
    with open(pyproject_path) as f:
        pyproject = toml.load(f)

    # Update the version
    pyproject["project"]["version"] = new_version

    # Write back to file
    with open(pyproject_path, "w") as f:
        toml.dump(pyproject, f)

    # Update __init__.py
    init_path = Path("querymate/__init__.py")
    if not init_path.exists():
        raise FileNotFoundError("querymate/__init__.py not found")

    # Read the file
    with open(init_path) as f:
        content = f.read()

    # Update the version line
    import re
    content = re.sub(
        r'__version__ = ".*?"',
        f'__version__ = "{new_version}"',
        content
    )

    # Write back to file
    with open(init_path, "w") as f:
        f.write(content)

    print(f"Updated version to {new_version} in both pyproject.toml and __init__.py")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_version.py <new_version>")
        sys.exit(1)

    new_version = sys.argv[1]
    update_version(new_version)
