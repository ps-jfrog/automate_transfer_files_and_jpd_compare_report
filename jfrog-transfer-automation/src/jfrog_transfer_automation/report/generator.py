from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from jfrog_transfer_automation.jfrog.artifactory_api import ArtifactoryClient
from jfrog_transfer_automation.jfrog.cli import JFrogCLI
from jfrog_transfer_automation.report.compare_adapter import (
    compare_repositories,
    generate_detailed_comparison_report,
)


@dataclass
class ReportResult:
    report_path: Path
    summary_path: Path


def _write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, indent=2))


def _repo_names(repos: List[Dict]) -> List[str]:
    names = [repo.get("key") for repo in repos if repo.get("key")]
    return sorted(set(names))


def generate_report(
    source_client: ArtifactoryClient,
    target_client: ArtifactoryClient,
    output_dir: Path,
    repo_type: Union[str, List[str]],
    detailed_comparison: bool = False,
    repos_file_for_comparison: Optional[str] = None,
    enable_aql_queries: bool = False,
    source_server_id: Optional[str] = None,
    target_server_id: Optional[str] = None,
    jf_cli: Optional[JFrogCLI] = None,
) -> ReportResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ts_suffix = f"-{timestamp}"

    source_client.calculate_storage()
    target_client.calculate_storage()

    source_storage = source_client.get_storageinfo()
    target_storage = target_client.get_storageinfo()
    source_repos = _repo_names(source_client.get_repositories(repo_type))
    target_repos = _repo_names(target_client.get_repositories(repo_type))

    source_storage_path = output_dir / f"source-storageinfo{ts_suffix}.json"
    target_storage_path = output_dir / f"target-storageinfo{ts_suffix}.json"
    _write_json(source_storage_path, source_storage)
    _write_json(target_storage_path, target_storage)
    (output_dir / f"all-local-repo-source{ts_suffix}.txt").write_text("\n".join(source_repos))

    missing_in_target = sorted(set(source_repos) - set(target_repos))
    missing_in_source = sorted(set(target_repos) - set(source_repos))

    summary = {
        "source_repo_count": len(source_repos),
        "target_repo_count": len(target_repos),
        "missing_in_target": missing_in_target,
        "missing_in_source": missing_in_source,
        "source_storage": source_storage.get("storageSummary", {}),
        "target_storage": target_storage.get("storageSummary", {}),
    }
    summary_path = output_dir / "comparison-summary.json"
    _write_json(summary_path, summary)

    report_path = output_dir / f"comparison{ts_suffix}.txt"

    if detailed_comparison and repos_file_for_comparison and jf_cli and source_server_id and target_server_id:
        repos_file_path = Path(repos_file_for_comparison).expanduser()
        if repos_file_path.exists():
            try:
                comparisons = compare_repositories(
                    source_storage_path,
                    target_storage_path,
                    repos_file_path,
                    source_server_id,
                    target_server_id,
                    jf_cli,
                    enable_aql=enable_aql_queries,
                )
                generate_detailed_comparison_report(comparisons, report_path)

                summary["detailed_comparison"] = {
                    "total_repos_compared": len(comparisons),
                    "repos_with_space_diff": len([c for c in comparisons if c.space_difference > 0]),
                    "repos_with_both_diff": len([
                        c for c in comparisons
                        if c.space_difference > 0 and c.source_files_count - c.target_files_count > 0
                    ]),
                }
                _write_json(summary_path, summary)
                return ReportResult(report_path=report_path, summary_path=summary_path)
            except Exception as e:
                report_lines = [
                    "JFrog Transfer Comparison Report",
                    "",
                    f"Error during detailed comparison: {e}",
                    "",
                    "Falling back to basic comparison:",
                    "",
                    f"Source repo count: {len(source_repos)}",
                    f"Target repo count: {len(target_repos)}",
                    "",
                    "Missing in target:",
                    *(missing_in_target or ["(none)"]),
                    "",
                    "Missing in source:",
                    *(missing_in_source or ["(none)"]),
                ]
                report_path.write_text("\n".join(report_lines))
        else:
            report_lines = [
                "JFrog Transfer Comparison Report",
                "",
                f"Repos file not found: {repos_file_path}",
                "Falling back to basic comparison:",
                "",
                f"Source repo count: {len(source_repos)}",
                f"Target repo count: {len(target_repos)}",
                "",
                "Missing in target:",
                *(missing_in_target or ["(none)"]),
                "",
                "Missing in source:",
                *(missing_in_source or ["(none)"]),
            ]
            report_path.write_text("\n".join(report_lines))
    else:
        report_lines = [
            "JFrog Transfer Comparison Report",
            "",
            f"Source repo count: {len(source_repos)}",
            f"Target repo count: {len(target_repos)}",
            "",
            "Missing in target:",
            *(missing_in_target or ["(none)"]),
            "",
            "Missing in source:",
            *(missing_in_source or ["(none)"]),
        ]
        report_path.write_text("\n".join(report_lines))

    return ReportResult(report_path=report_path, summary_path=summary_path)
