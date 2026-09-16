from typing import Optional

from jfrog_transfer_automation.config.model import AppConfig, JFrogConfig, TransferConfig
from jfrog_transfer_automation.jfrog.cli import JFrogCLI
from jfrog_transfer_automation.transfer.runner import TransferRunner


def _runner(transfer: Optional[TransferConfig] = None) -> TransferRunner:
    config = AppConfig(
        jfrog=JFrogConfig(source_server_id="src", target_server_id="dst"),
        transfer=transfer or TransferConfig(),
    )
    return TransferRunner(config, JFrogCLI())


def test_build_transfer_args_omits_date_filters_by_default() -> None:
    args = _runner()._build_transfer_args(["repo-a"])
    assert "--created-after" not in args
    assert "--downloaded-after" not in args
    assert args == [
        "rt",
        "transfer-files",
        "--include-repos",
        "repo-a",
        "--ignore-state=false",
        "--filestore",
        "src",
        "dst",
    ]


def test_build_transfer_args_includes_created_after() -> None:
    runner = _runner(TransferConfig(created_after="2024-01-15T00:00:00.000Z"))
    args = runner._build_transfer_args(["repo-a", "repo-b"])
    created_idx = args.index("--created-after")
    assert args[created_idx + 1] == "2024-01-15T00:00:00.000Z"
    assert "--downloaded-after" not in args


def test_build_transfer_args_includes_downloaded_after() -> None:
    runner = _runner(TransferConfig(downloaded_after="2024-02-01T12:30:00.000Z"))
    args = runner._build_transfer_args(["repo-a"])
    downloaded_idx = args.index("--downloaded-after")
    assert args[downloaded_idx + 1] == "2024-02-01T12:30:00.000Z"
    assert "--created-after" not in args


def test_build_transfer_args_passes_both_date_filters() -> None:
    runner = _runner(
        TransferConfig(
            created_after="2024-01-15T00:00:00.000Z",
            downloaded_after="2024-02-01T12:30:00.000Z",
        )
    )
    args = runner._build_transfer_args(["repo-a"])
    assert args[args.index("--created-after") + 1] == "2024-01-15T00:00:00.000Z"
    assert args[args.index("--downloaded-after") + 1] == "2024-02-01T12:30:00.000Z"
