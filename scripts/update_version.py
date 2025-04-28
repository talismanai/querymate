#!/usr/bin/env python3
import sys
import toml
from pathlib import Path

def update_version(new_version: str) -> None:
    """Update the version in pyproject.toml."""
    # Load the current pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found")
    
    # Read and parse the file
    with open(pyproject_path, "r") as f:
        pyproject = toml.load(f)
    
    # Update the version
    pyproject["project"]["version"] = new_version
    
    # Write back to file
    with open(pyproject_path, "w") as f:
        toml.dump(pyproject, f)
    
    print(f"Updated version to {new_version}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_version.py <new_version>")
        sys.exit(1)
    
    new_version = sys.argv[1]
    update_version(new_version) 