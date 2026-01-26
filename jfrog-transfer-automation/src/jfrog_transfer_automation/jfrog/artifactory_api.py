from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Union

import requests

logger = logging.getLogger(__name__)


@dataclass
class ArtifactoryClient:
    base_url: str
    access_token: str
    verify_ssl: bool = True
    timeout_seconds: int = 60
    storage_calculation_wait_seconds: int = 0

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def _artifactory_api_url(self, endpoint: str) -> str:
        """
        Construct Artifactory API URL, handling both platform URL and Artifactory URL formats.
        
        Args:
            endpoint: API endpoint path (e.g., "api/storageinfo/calculate")
        
        Returns:
            Full URL to the API endpoint
        """
        base = self.base_url.rstrip("/")
        # Check if base_url already includes /artifactory
        if base.endswith("/artifactory"):
            # Already has /artifactory, just append the endpoint
            return f"{base}/{endpoint}"
        else:
            # Platform URL, need to add /artifactory
            return f"{base}/artifactory/{endpoint}"

    def calculate_storage(self, wait_seconds: int = 0) -> None:
        """
        Calculate storage info and optionally wait for calculation to complete.
        
        Args:
            wait_seconds: Fixed wait time after API call (default: use instance config)
        """
        url = self._artifactory_api_url("api/storageinfo/calculate")
        response = requests.post(
            url,
            headers=self._headers(),
            timeout=self.timeout_seconds,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        
        response_data = response.json()
        logger.info(f"Storage calculation scheduled: {response_data.get('info', 'N/A')}")
        
        # Use instance config if not provided
        wait_seconds = wait_seconds or self.storage_calculation_wait_seconds
        
        # Fixed wait time
        if wait_seconds > 0:
            logger.info(f"Waiting {wait_seconds} seconds for storage calculation to complete...")
            time.sleep(wait_seconds)
            logger.info("Storage calculation wait completed")

    def get_storageinfo(self) -> Dict[str, Any]:
        url = self._artifactory_api_url("api/storageinfo")
        response = requests.get(
            url,
            headers=self._headers(),
            timeout=self.timeout_seconds,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def get_repositories(self, repo_type: Union[str, List[str]]) -> List[Dict[str, Any]]:
        """
        Get repositories by type(s).
        
        Args:
            repo_type: Single type string (e.g., "local") or list of types (e.g., ["local", "federated"])
        
        Returns:
            Combined list of all repositories matching the type(s), deduplicated by repo key
        """
        if isinstance(repo_type, list):
            all_repos = []
            seen_keys = set()
            for rt in repo_type:
                repos = self._get_repositories_single_type(rt)
                for repo in repos:
                    repo_key = repo.get("key")
                    if repo_key and repo_key not in seen_keys:
                        seen_keys.add(repo_key)
                        all_repos.append(repo)
            return all_repos
        else:
            return self._get_repositories_single_type(repo_type)
    
    def _get_repositories_single_type(self, repo_type: str) -> List[Dict[str, Any]]:
        """Get repositories for a single type."""
        url = self._artifactory_api_url(f"api/repositories?type={repo_type}")
        response = requests.get(
            url,
            headers=self._headers(),
            timeout=self.timeout_seconds,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()
