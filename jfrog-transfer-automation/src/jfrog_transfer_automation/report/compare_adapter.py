from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jfrog_transfer_automation.jfrog.cli import JFrogCLI


@dataclass
class RepoComparison:
    repo_key: str
    source_repo_type: str
    source_package_type: str
    source_files_count: int
    target_files_count: int
    source_space_bytes: int
    target_space_bytes: int
    space_difference: int
    transfer_percentage: float


def convert_used_space_to_bytes(used_space_str: str) -> int:
    """Convert used space with units (MB, GB, TB) to bytes."""
    if not used_space_str or used_space_str == "N/A":
        return 0
    if "MB" in used_space_str:
        return int(float(used_space_str.replace(" MB", "")) * 1024 * 1024)
    elif "GB" in used_space_str:
        return int(float(used_space_str.replace(" GB", "")) * 1024 * 1024 * 1024)
    elif "TB" in used_space_str:
        return int(float(used_space_str.replace(" TB", "")) * 1024 * 1024 * 1024 * 1024)
    elif "bytes" in used_space_str:
        return int(float(used_space_str.replace(" bytes", "")))
    elif "KB" in used_space_str:
        return int(float(used_space_str.replace(" KB", "")) * 1024)
    else:
        try:
            return int(float(used_space_str))
        except (ValueError, TypeError):
            return 0


def extract_repo_details(
    repo_keys: List[str], source_data: Dict, target_data: Dict
) -> List[Dict]:
    """Extract repository details from source and target storageinfo."""
    source_dict = {
        repo["repoKey"]: repo
        for repo in source_data.get("repositoriesSummaryList", [])
    }
    target_dict = {
        repo["repoKey"]: repo
        for repo in target_data.get("repositoriesSummaryList", [])
    }

    repo_details = []
    for repo_key in repo_keys:
        source_repo = source_dict.get(repo_key)
        target_repo = target_dict.get(repo_key)

        if source_repo or target_repo:
            repo_details.append({
                "repoKey": repo_key,
                "source": source_repo,
                "target": target_repo,
            })

    return repo_details


def get_space_bytes(repo_details: Optional[Dict], source_has_bytes: bool) -> int:
    """Get space in bytes from repo details."""
    if not repo_details:
        return 0

    if source_has_bytes and "usedSpaceInBytes" in repo_details:
        return int(repo_details.get("usedSpaceInBytes", 0))
    elif "usedSpace" in repo_details:
        return convert_used_space_to_bytes(str(repo_details.get("usedSpace", "0")))
    else:
        return 0


def execute_aql_query_simple(
    jf_cli: JFrogCLI,
    repo_key: str,
    server_id: str,
    aql_query: str,
) -> Tuple[int, int]:
    """Execute AQL query and return (item_count, total_size_bytes)."""
    args = [
        "rt",
        "curl",
        "-s",
        "-XPOST",
        "/api/search/aql",
        "-H",
        "Content-Type: text/plain",
        "-d",
        aql_query,
        "-L",
        "--server-id",
        server_id,
    ]

    result = jf_cli.run(args)
    if result.returncode != 0:
        return 0, 0

    try:
        data = json.loads(result.stdout)
        results = data.get("results", [])
        total_size = sum(item.get("size", 0) for item in results)
        item_count = len(results)
        return item_count, total_size
    except (json.JSONDecodeError, KeyError):
        return 0, 0


def get_docker_uploads_exclusion(
    jf_cli: JFrogCLI,
    repo_key: str,
    server_id: str,
) -> Tuple[int, int]:
    """Get Docker repo uploads/catalog files count and size to exclude."""
    aql_query = f'''items.find(
        {{ "repo": "{repo_key}",
             "$or": [
                {{"name": {{"$match": "repository.catalog"}}}},
                {{"path": {{"$match": ".jfrog"}}}},
                {{"path": {{"$match": "*_uploads"}}}}
            ]
        }}
    )'''
    return execute_aql_query_simple(jf_cli, repo_key, server_id, aql_query)


def get_dot_folders_exclusion(
    jf_cli: JFrogCLI,
    repo_key: str,
    server_id: str,
) -> Tuple[int, int]:
    """Get non-Docker repo dot folder files count and size to exclude."""
    aql_query = f'''items.find(
        {{
            "repo": "{repo_key}",
            "$and": [
                {{"path": {{"$match": ".*"}}}},
                {{"path": {{"$ne": "."}}}}
            ]
        }}
    )'''
    return execute_aql_query_simple(jf_cli, repo_key, server_id, aql_query)


def compare_repositories(
    source_storage_path: Path,
    target_storage_path: Path,
    repos_file_path: Path,
    source_server_id: str,
    target_server_id: str,
    jf_cli: JFrogCLI,
    enable_aql: bool = False,
) -> List[RepoComparison]:
    """
    Compare repositories between source and target.

    Args:
        source_storage_path: Path to source storageinfo JSON
        target_storage_path: Path to target storageinfo JSON
        repos_file_path: Path to file with repo keys (one per line)
        source_server_id: Source JFrog server ID
        target_server_id: Target JFrog server ID
        jf_cli: JFrogCLI instance
        enable_aql: Whether to run AQL queries for Docker/dot folder exclusions

    Returns:
        List of RepoComparison objects
    """
    with open(source_storage_path) as f:
        source_data = json.load(f)
    with open(target_storage_path) as f:
        target_data = json.load(f)

    repo_keys = [
        line.strip()
        for line in open(repos_file_path).readlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    repo_details = extract_repo_details(repo_keys, source_data, target_data)

    source_has_bytes = any(
        "usedSpaceInBytes" in repo.get("source", {})
        for repo in repo_details
        if repo.get("source")
    )

    comparisons = []

    for repo_detail in repo_details:
        repo_key = repo_detail["repoKey"]
        source_repo = repo_detail.get("source", {})
        target_repo = repo_detail.get("target", {})

        source_repo_type = source_repo.get("repoType", "N/A")
        source_package_type = source_repo.get("packageType", "N/A")

        source_files_count = source_repo.get("filesCount", 0)
        target_files_count = target_repo.get("filesCount", 0)

        source_space_bytes = get_space_bytes(source_repo, source_has_bytes)
        target_space_bytes = get_space_bytes(target_repo, source_has_bytes)

        if enable_aql:
            if source_package_type == "Docker":
                source_uploads_count, source_uploads_size = get_docker_uploads_exclusion(
                    jf_cli, repo_key, source_server_id
                )
                target_uploads_count, target_uploads_size = get_docker_uploads_exclusion(
                    jf_cli, repo_key, target_server_id
                )
                source_files_count -= source_uploads_count
                target_files_count -= target_uploads_count
                source_space_bytes -= source_uploads_size
                target_space_bytes -= target_uploads_size
            else:
                source_dot_count, source_dot_size = get_dot_folders_exclusion(
                    jf_cli, repo_key, source_server_id
                )
                target_dot_count, target_dot_size = get_dot_folders_exclusion(
                    jf_cli, repo_key, target_server_id
                )
                source_files_count -= source_dot_count
                target_files_count -= target_dot_count
                source_space_bytes -= source_dot_size
                target_space_bytes -= target_dot_size

        space_difference = source_space_bytes - target_space_bytes
        transfer_percentage = (
            (space_difference / source_space_bytes * 100)
            if source_space_bytes != 0
            else 0.0
        )

        comparisons.append(
            RepoComparison(
                repo_key=repo_key,
                source_repo_type=source_repo_type,
                source_package_type=source_package_type,
                source_files_count=source_files_count,
                target_files_count=target_files_count,
                source_space_bytes=source_space_bytes,
                target_space_bytes=target_space_bytes,
                space_difference=space_difference,
                transfer_percentage=transfer_percentage,
            )
        )

    return sorted(comparisons, key=lambda x: x.space_difference, reverse=True)


def generate_detailed_comparison_report(
    comparisons: List[RepoComparison],
    output_path: Path,
) -> None:
    """Generate a detailed tabular comparison report."""
    lines = [
        "{:<64} {:<15} {:<15} {:<15} {:<15} {:<20} {:<20} {:<25} {:<20}".format(
            "Repo Key",
            "Source repoType",
            "Source packageType",
            "Source filesCount",
            "Target filesCount",
            "Used Space (Source)",
            "Used Space (Target)",
            "SpaceInBytes Difference",
            "Remaining Transfer %",
        ),
        "=" * 220,
    ]

    repos_with_space_diff = []
    repos_with_both_diff = []
    repos_with_negative_diff = []

    for comp in comparisons:
        if comp.space_difference > 0:
            repos_with_space_diff.append(comp.repo_key)
            if comp.source_files_count - comp.target_files_count > 0:
                repos_with_both_diff.append(comp.repo_key)
        elif comp.space_difference < 0:
            repos_with_negative_diff.append(comp.repo_key)

        lines.append(
            "{:<64} {:<25} {:<15} {:<15} {:<15} {:<20} {:<20} {:<25} {:<20.2f}".format(
                comp.repo_key,
                comp.source_repo_type,
                comp.source_package_type,
                comp.source_files_count,
                comp.target_files_count,
                comp.source_space_bytes,
                comp.target_space_bytes,
                comp.space_difference,
                comp.transfer_percentage,
            )
        )

    lines.extend([
        "",
        f"Repos with space difference > 0 ({len(repos_with_space_diff)} repos):",
        ";".join(sorted(repos_with_space_diff)),
        "",
        f"Repos with both space and file count differences > 0 ({len(repos_with_both_diff)} repos):",
        ";".join(sorted(repos_with_both_diff)),
        "",
        f"Repos with space difference < 0 ({len(repos_with_negative_diff)} repos):",
        ";".join(sorted(repos_with_negative_diff)),
    ])

    output_path.write_text("\n".join(lines))
