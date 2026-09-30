from pathlib import Path

from jfrog_transfer_automation.transfer.repo_list import load_repos


def test_load_repos_file(tmp_path: Path) -> None:
    repo_file = tmp_path / "repos.txt"
    repo_file.write_text(
        "\n".join(
            [
                "# comment",
                "repo-a",
                "",
                "repo-b",
                "  repo-c  ",
            ]
        )
    )

    repos = load_repos(str(repo_file))
    assert repos == ["repo-a", "repo-b", "repo-c"]
