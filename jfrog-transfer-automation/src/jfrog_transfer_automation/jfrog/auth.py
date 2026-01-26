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
    # First check if server exists
    show = jf_cli.run(["c", "show", server_id])
    if show.returncode != 0:
        # Try to get list of available servers for helpful error message
        list_result = jf_cli.run(["c", "show"])
        available_servers = []
        if list_result.returncode == 0 and list_result.stdout:
            # Parse available servers from output
            for line in list_result.stdout.splitlines():
                if line.strip() and not line.startswith("Server ID"):
                    parts = line.split()
                    if parts:
                        available_servers.append(parts[0])
        
        error_msg = f"Server ID '{server_id}' not found in JFrog CLI configuration."
        if available_servers:
            error_msg += f"\nAvailable server IDs: {', '.join(available_servers)}"
        error_msg += f"\nTo add this server, run: jf c add {server_id}"
        raise RuntimeError(error_msg)

    export = jf_cli.run(["c", "export", server_id])
    if export.returncode != 0 or not export.stdout:
        raise RuntimeError(
            f"Failed to export JFrog CLI config for server ID '{server_id}'. "
            f"Error: {export.stderr or 'Unknown error'}"
        )

    try:
        decoded = base64.b64decode(export.stdout.encode("utf-8")).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"Failed to parse JFrog CLI config for server ID '{server_id}': {e}"
        )

    # Handle different export formats:
    # 1. Nested format: {"servers": {"server_id": {...}}}
    # 2. Flat format: {"serverId": "server_id", "url": "...", ...}
    # 3. Direct format: {"server_id": {...}}
    server = None
    if "servers" in payload and isinstance(payload["servers"], dict):
        server = payload["servers"].get(server_id)
    elif payload.get("serverId") == server_id:
        # Flat format - the payload itself is the server config
        server = payload
    else:
        # Try direct lookup
        server = payload.get(server_id)
    
    if not server:
        raise RuntimeError(
            f"Server config not found in exported data for server ID '{server_id}'. "
            f"Please verify the server is properly configured: jf c show {server_id}"
        )

    # Extract URL - prefer artifactoryUrl, fall back to url
    url = server.get("artifactoryUrl") or server.get("url") or ""
    if url:
        url = url.rstrip("/")
    # Extract access token - try different field names
    access_token = server.get("accessToken") or server.get("access_token")
    if not url or not access_token:
        missing = []
        if not url:
            missing.append("url")
        if not access_token:
            missing.append("accessToken")
        raise RuntimeError(
            f"Incomplete server config for server ID '{server_id}'. "
            f"Missing: {', '.join(missing)}. "
            f"Please reconfigure: jf c add {server_id}"
        )

    return JFrogCredentials(url=url, access_token=access_token)
