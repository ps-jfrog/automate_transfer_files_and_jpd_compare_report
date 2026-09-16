from jfrog_transfer_automation.config.loader import apply_env_overrides, load_config


def test_load_config_defaults(tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("schedule:\n  start_time: \"01:00\"\n")
    config = load_config(str(config_file))
    assert config.schedule.start_time == "01:00"
    assert config.jfrog.jfrog_cli_path == "jf"
    assert config.transfer.created_after is None
    assert config.transfer.downloaded_after is None


def test_load_config_transfer_date_filters(tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "transfer:\n"
        "  created_after: \"2024-01-15T00:00:00.000Z\"\n"
        "  downloaded_after: \"2024-02-01T12:30:00.000Z\"\n"
    )
    config = load_config(str(config_file))
    assert config.transfer.created_after == "2024-01-15T00:00:00.000Z"
    assert config.transfer.downloaded_after == "2024-02-01T12:30:00.000Z"


def test_env_overrides(monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("schedule:\n  start_time: \"01:00\"\n")
    config = load_config(str(config_file))
    monkeypatch.setenv("JFROG_SOURCE_ACCESS_TOKEN", "source-token")
    monkeypatch.setenv("JFROG_TARGET_ACCESS_TOKEN", "target-token")
    config = apply_env_overrides(config)
    assert config.jfrog.source_access_token == "source-token"
    assert config.jfrog.target_access_token == "target-token"
