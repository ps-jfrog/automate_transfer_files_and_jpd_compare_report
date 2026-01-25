from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def load_repos(file_path: str, inline: Optional[List[str]] = None) -> List[str]:
    if inline:
        return [repo.strip() for repo in inline if repo and repo.strip()]

    path = Path(file_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Repo list not found: {path}")

    repos: List[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        repos.append(stripped)

    if not repos:
        raise ValueError("Repo list is empty after filtering")

    return repos
