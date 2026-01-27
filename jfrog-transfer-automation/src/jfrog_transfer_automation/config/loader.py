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
    import logging
    logger = logging.getLogger("jfrog_transfer_automation")
    
    config_path = Path(path).expanduser().resolve()
    logger.debug(f"Loading config from: {config_path}")
    logger.debug(f"Config file exists: {config_path.exists()}")
    
    raw: Dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text()) or {}
        logger.debug(f"Loaded YAML keys: {list(raw.keys())}")
        if "transfer" in raw:
            logger.debug(f"Transfer config from YAML: {raw['transfer']}")
    else:
        logger.warning(f"Config file not found: {config_path}")

    schedule = ScheduleConfig(**(raw.get("schedule") or {}))
    jfrog = JFrogConfig(**(raw.get("jfrog") or {}))
    
    # Resolve relative paths relative to config file location
    config_dir = config_path.parent
    
    transfer_raw = raw.get("transfer") or {}
    # Resolve include_repos_file - try multiple resolution strategies
    # Only resolve relative to config file if path starts with ./ or is just a filename
    # Paths with directory components are assumed to be relative to project root/CWD
    if "include_repos_file" in transfer_raw and transfer_raw["include_repos_file"]:
        include_repos_file = transfer_raw["include_repos_file"]
        if not Path(include_repos_file).is_absolute():
            # Only resolve relative to config file if it starts with ./ or is just a filename
            # This indicates it's meant to be relative to the config file location
            if include_repos_file.startswith("./") or "/" not in include_repos_file:
                resolved_path = (config_dir / include_repos_file).resolve()
                transfer_raw["include_repos_file"] = str(resolved_path)
                logger.debug(f"Resolved include_repos_file relative to config file: {transfer_raw['include_repos_file']}")
            else:
                # Path has directory components - assume it's relative to project root/CWD
                # Don't resolve it, let load_repos handle it (it will check relative to CWD)
                logger.debug(f"Keeping include_repos_file as-is (has directory components, relative to CWD): {include_repos_file}")
    
    logger.debug(f"Creating TransferConfig with: {transfer_raw}")
    transfer = TransferConfig(**transfer_raw)
    logger.debug(f"TransferConfig created - ignore_state: {transfer.ignore_state} (type: {type(transfer.ignore_state)})")
    
    report_raw = raw.get("report") or {}
    # Resolve output_dir relative to config file location if it's a relative path
    output_dir = report_raw.get("output_dir", "./runs")
    if not Path(output_dir).is_absolute():
        # Resolve relative to config file's directory
        output_dir = str((config_dir / output_dir).resolve())
        logger.debug(f"Resolved output_dir relative to config file: {output_dir}")
    else:
        output_dir = str(Path(output_dir).expanduser().resolve())
        logger.debug(f"Using absolute output_dir: {output_dir}")
    
    # Resolve repos_file_for_comparison relative to config file if it's a relative path
    repos_file_for_comparison = report_raw.get("repos_file_for_comparison")
    if repos_file_for_comparison and not Path(repos_file_for_comparison).is_absolute():
        repos_file_for_comparison = str((config_dir / repos_file_for_comparison).resolve())
        logger.debug(f"Resolved repos_file_for_comparison relative to config file: {repos_file_for_comparison}")
    
    report = ReportConfig(
        enabled=report_raw.get("enabled", True),
        repo_type=report_raw.get("repo_type", "local"),
        output_dir=output_dir,
        detailed_comparison=report_raw.get("detailed_comparison", False),
        repos_file_for_comparison=repos_file_for_comparison,
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
