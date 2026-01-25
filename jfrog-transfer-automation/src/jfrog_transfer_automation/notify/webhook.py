from __future__ import annotations

from typing import Dict

import requests


def post_webhook(url: str, payload: Dict, headers: Dict | None = None) -> None:
    response = requests.post(url, json=payload, headers=headers or {}, timeout=30)
    response.raise_for_status()
