"""
Plex library scan checker.
Queries the Plex API to determine if a library containing a given file is currently scanning.
"""

import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class PlexScanChecker:
    """Checks whether Plex is currently scanning a library that contains a given file."""

    def __init__(
        self,
        plex_url: str,
        plex_token: str,
        path_mappings: List[Tuple[str, str]] = None,
        check_interval: int = 30,
        check_timeout: int = 3600,
    ):
        self.plex_url = plex_url.rstrip('/')
        self.plex_token = plex_token
        self.path_mappings = path_mappings or []
        self.check_interval = check_interval
        self.check_timeout = check_timeout
        logger.info(f"Plex scan checker initialized: {self.plex_url}")
        if self.path_mappings:
            for container_path, plex_path in self.path_mappings:
                logger.info(f"  Plex path mapping: {container_path} -> {plex_path}")

    def _map_to_plex_path(self, container_path: str) -> str:
        """Translate a container file path to a Plex-visible path."""
        for container_prefix, plex_prefix in self.path_mappings:
            if container_path.startswith(container_prefix):
                mapped = plex_prefix + container_path[len(container_prefix):]
                logger.debug(f"Plex path mapped: {container_path} -> {mapped}")
                return mapped
        return container_path

    def _fetch_library_sections(self) -> ET.Element:
        """Fetch /library/sections from Plex and return parsed XML root."""
        url = f"{self.plex_url}/library/sections?X-Plex-Token={self.plex_token}"
        req = urllib.request.Request(url)
        req.add_header('Accept', 'application/xml')
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read()
        return ET.fromstring(data)

    def _is_library_scanning_for_path(self, plex_path: str) -> Tuple[bool, Optional[str]]:
        """
        Check if any Plex library that contains plex_path is currently scanning.

        Returns (is_scanning, library_title).
        """
        try:
            root = self._fetch_library_sections()
        except Exception as e:
            logger.warning(f"Failed to query Plex library sections: {e}")
            return (False, None)

        for directory in root.findall('.//Directory'):
            title = directory.get('title', 'Unknown')
            refreshing = directory.get('refreshing', '0')

            for location in directory.findall('Location'):
                loc_path = location.get('path', '')
                if plex_path.startswith(loc_path):
                    if refreshing == '1':
                        return (True, title)
                    else:
                        return (False, title)

        logger.debug(f"No Plex library found containing path: {plex_path}")
        return (False, None)

    def wait_if_scanning(self, file_path: str) -> None:
        """
        If Plex is scanning the library containing file_path, wait until it finishes.

        This is the main public method. Call it right before os.replace().
        On any error, logs a warning and returns immediately (fail open).
        """
        plex_path = self._map_to_plex_path(file_path)
        elapsed = 0

        while True:
            try:
                is_scanning, library_title = self._is_library_scanning_for_path(plex_path)
            except Exception as e:
                logger.warning(f"Plex scan check error, proceeding with file replacement: {e}")
                return

            if not is_scanning:
                if elapsed > 0:
                    logger.info(
                        f"Plex library '{library_title}' scan finished after waiting {elapsed}s"
                    )
                return

            if elapsed >= self.check_timeout:
                logger.warning(
                    f"Plex library '{library_title}' still scanning after {elapsed}s "
                    f"(timeout {self.check_timeout}s). Proceeding with file replacement."
                )
                return

            logger.info(
                f"Plex library '{library_title}' is scanning. "
                f"Waiting {self.check_interval}s before rechecking... "
                f"({elapsed}s / {self.check_timeout}s timeout)"
            )
            time.sleep(self.check_interval)
            elapsed += self.check_interval
