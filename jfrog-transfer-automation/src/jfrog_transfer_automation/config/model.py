from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class ScheduleConfig:
    timezone: str = "America/Los_Angeles"
    start_time: str = ""
    end_time: Optional[str] = None
    run_on_startup: bool = False
    catch_up_if_missed: bool = False


@dataclass
class JFrogConfig:
    jfrog_cli_path: str = "jf"
    source_server_id: str = ""
    target_server_id: str = ""
    source_url: Optional[str] = None
    target_url: Optional[str] = None
    source_access_token: Optional[str] = None
    target_access_token: Optional[str] = None
    verify_ssl: bool = True
    timeout_seconds: int = 60


@dataclass
class TransferConfig:
    include_repos_file: str = "repos.txt"
    include_repos_inline: Optional[List[str]] = None
    mode: str = "single_command"
    threads: int = 8
    filestore: bool = True
    ignore_state: bool = False
    batch_size: int = 4
    stuck_timeout_seconds: int = 600
    poll_interval_seconds: int = 60
    jfrog_cli_home_strategy: str = "default"
    cli_log_level: str = "INFO"  # DEBUG, INFO, WARN, ERROR


@dataclass
class ReportConfig:
    enabled: bool = True
    repo_type: Union[str, List[str]] = "local"  # Can be "local", "federated", or ["local", "federated"]
    output_dir: str = "./runs"
    detailed_comparison: bool = False
    repos_file_for_comparison: Optional[str] = None
    enable_aql_queries: bool = False
    storage_calculation_wait_seconds: int = 0  # Wait time (seconds) after calculate_storage() API call


@dataclass
class EmailConfig:
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password_env: str = "SMTP_PASSWORD"
    to: List[str] = field(default_factory=list)
    from_address: str = "jfrog-automation@example.com"


@dataclass
class WebhookConfig:
    url: str = ""
    headers: dict = field(default_factory=dict)


@dataclass
class NotifyConfig:
    method: str = "none"
    email: EmailConfig = field(default_factory=EmailConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)


@dataclass
class AppConfig:
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    jfrog: JFrogConfig = field(default_factory=JFrogConfig)
    transfer: TransferConfig = field(default_factory=TransferConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
