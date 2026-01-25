from jfrog_transfer_automation.config.loader import apply_env_overrides, load_config


def test_load_config_defaults(tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("schedule:\n  start_time: \"01:00\"\n")
    config = load_config(str(config_file))
    assert config.schedule.start_time == "01:00"
    assert config.jfrog.jfrog_cli_path == "jf"


def test_env_overrides(monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("schedule:\n  start_time: \"01:00\"\n")
    config = load_config(str(config_file))
    monkeypatch.setenv("JFROG_SOURCE_ACCESS_TOKEN", "source-token")
    monkeypatch.setenv("JFROG_TARGET_ACCESS_TOKEN", "target-token")
    config = apply_env_overrides(config)
    assert config.jfrog.source_access_token == "source-token"
    assert config.jfrog.target_access_token == "target-token"
