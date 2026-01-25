from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

from jfrog_transfer_automation.config.model import (
    AppConfig,
    EmailConfig,
    JFrogConfig,
    NotifyConfig,
    ReportConfig,
    ScheduleConfig,
    TransferConfig,
    WebhookConfig,
)


def _merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge(base.get(key, {}), value)
        else:
            base[key] = value
    return base


def load_config(path: str) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    raw: Dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text()) or {}

    schedule = ScheduleConfig(**(raw.get("schedule") or {}))
    jfrog = JFrogConfig(**(raw.get("jfrog") or {}))
    transfer = TransferConfig(**(raw.get("transfer") or {}))
    report_raw = raw.get("report") or {}
    report = ReportConfig(
        enabled=report_raw.get("enabled", True),
        repo_type=report_raw.get("repo_type", "local"),
        output_dir=report_raw.get("output_dir", "./runs"),
        detailed_comparison=report_raw.get("detailed_comparison", False),
        repos_file_for_comparison=report_raw.get("repos_file_for_comparison"),
        enable_aql_queries=report_raw.get("enable_aql_queries", False),
        storage_calculation_wait_seconds=int(report_raw.get("storage_calculation_wait_seconds", 0)),
    )

    email_raw = raw.get("notify", {}).get("email", {}) if raw.get("notify") else {}
    email = EmailConfig(
        smtp_host=email_raw.get("smtp_host", ""),
        smtp_port=int(email_raw.get("smtp_port", 587)),
        smtp_user=email_raw.get("smtp_user", ""),
        smtp_password_env=email_raw.get("smtp_password_env", "SMTP_PASSWORD"),
        to=email_raw.get("to", []),
        from_address=email_raw.get("from", "jfrog-automation@example.com"),
    )

    webhook_raw = raw.get("notify", {}).get("webhook", {}) if raw.get("notify") else {}
    webhook = WebhookConfig(
        url=webhook_raw.get("url", ""),
        headers=webhook_raw.get("headers", {}),
    )

    notify = NotifyConfig(
        method=(raw.get("notify") or {}).get("method", "none"),
        email=email,
        webhook=webhook,
    )

    return AppConfig(
        schedule=schedule,
        jfrog=jfrog,
        transfer=transfer,
        report=report,
        notify=notify,
    )


def apply_env_overrides(config: AppConfig) -> AppConfig:
    # Allow explicit token overrides for restricted environments
    source_token = os.environ.get("JFROG_SOURCE_ACCESS_TOKEN")
    target_token = os.environ.get("JFROG_TARGET_ACCESS_TOKEN")
    if source_token:
        config.jfrog.source_access_token = source_token
    if target_token:
        config.jfrog.target_access_token = target_token

    return config
