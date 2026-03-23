"""Shared fixtures and CLI options for integration tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from jfrog_transfer_automation.config.loader import load_config
from jfrog_transfer_automation.jfrog.auth import extract_cli_config
from jfrog_transfer_automation.jfrog.cli import JFrogCLI
from jfrog_transfer_automation.transfer.repo_list import load_repos


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--config",
        required=True,
        help="Path to jfrog-transfer-automation config YAML (e.g. test_schedule/config.yaml)",
    )
    parser.addoption(
        "--docker-generator",
        default=None,
        help="Path to docker_image_generator.py (seed test data step)",
    )
    parser.addoption(
        "--docker-username",
        default="admin",
        help="Docker registry username for seeding (default: admin)",
    )
    parser.addoption(
        "--image-count",
        type=int,
        default=4,
        help="Number of Docker images to publish per repo (default: 4)",
    )
    parser.addoption(
        "--image-size-mb",
        type=int,
        default=10,
        help="Size in MB of each Docker image (default: 10)",
    )


@pytest.fixture(scope="session")
def config_path(request: pytest.FixtureRequest) -> Path:
    path = Path(request.config.getoption("--config")).resolve()
    if not path.exists():
        pytest.fail(f"Config file not found: {path}")
    return path


@pytest.fixture(scope="session")
def app_config(config_path: Path):
    return load_config(str(config_path))


@pytest.fixture(scope="session")
def source_creds(app_config):
    jf_cli = JFrogCLI(app_config.jfrog.jfrog_cli_path)
    return extract_cli_config(jf_cli, app_config.jfrog.source_server_id)


@pytest.fixture(scope="session")
def repos(app_config, config_path: Path) -> list[str]:
    repos_file = Path(config_path).parent / app_config.transfer.include_repos_file
    return load_repos(str(repos_file))


@pytest.fixture(scope="session")
def docker_generator(request: pytest.FixtureRequest) -> Path | None:
    val = request.config.getoption("--docker-generator")
    if val is None:
        return None
    path = Path(val).resolve()
    if not path.exists():
        pytest.fail(f"docker_image_generator.py not found: {path}")
    return path


@pytest.fixture(scope="session")
def docker_username(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--docker-username")


@pytest.fixture(scope="session")
def image_count(request: pytest.FixtureRequest) -> int:
    return request.config.getoption("--image-count")


@pytest.fixture(scope="session")
def image_size_mb(request: pytest.FixtureRequest) -> int:
    return request.config.getoption("--image-size-mb")
