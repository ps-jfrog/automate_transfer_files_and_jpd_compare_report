from pathlib import Path

from jfrog_transfer_automation.report.generator import generate_report


class FakeClient:
    def __init__(self, repos):
        self._repos = repos

    def calculate_storage(self) -> None:
        return None

    def get_storageinfo(self):
        return {"storageSummary": {"repoCount": len(self._repos)}}

    def get_repositories(self, _repo_type):
        return [{"key": repo} for repo in self._repos]


def test_generate_report(tmp_path: Path) -> None:
    source = FakeClient(["a", "b"])
    target = FakeClient(["b", "c"])
    result = generate_report(source, target, tmp_path, "local")
    assert result.report_path.exists()
    assert result.summary_path.exists()
