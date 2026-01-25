from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from jfrog_transfer_automation.jfrog.cli import JFrogCLI


@dataclass
class JFrogCredentials:
    url: str
    access_token: str


def extract_cli_config(jf_cli: JFrogCLI, server_id: str) -> JFrogCredentials:
    show = jf_cli.run(["c", "show", server_id])
    if show.returncode != 0:
        raise RuntimeError(f"Server ID not found in JFrog CLI: {server_id}")

    export = jf_cli.run(["c", "export", server_id])
    if export.returncode != 0 or not export.stdout:
        raise RuntimeError(f"Failed to export JFrog CLI config for: {server_id}")

    decoded = base64.b64decode(export.stdout.encode("utf-8")).decode("utf-8")
    payload = json.loads(decoded)
    server = payload.get("servers", {}).get(server_id) or payload.get(server_id)
    if not server:
        raise RuntimeError(f"Server config not found for: {server_id}")

    url = (server.get("url") or "").rstrip("/")
    access_token = server.get("accessToken") or server.get("access_token")
    if not url or not access_token:
        raise RuntimeError(f"Incomplete server config for: {server_id}")

    return JFrogCredentials(url=url, access_token=access_token)
