import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Callable
from urllib.parse import urlparse

from .cache import Cache
from .logger import Logger
from .models import ExternalLink


class ExternalLinksDownloader:
    """Download external links (e.g. Google Drive)"""

    def __init__(self, logger: Logger):
        self.logger = logger

    # ------------------------------------------------------------------
    # Google Drive helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_allowed_domain(link: ExternalLink, allowed_domains: List[str], filtered_artists: List[str]) -> bool:
        return any(d in link.domain or d in link.url for d in allowed_domains) and link.artist_id not in filtered_artists

    @staticmethod
    def _extract_gdrive_id(url: str) -> Optional[str]:
        """Extract Google Drive file or folder ID from URL"""
        import re

        patterns = [
            r"/file/d/([^/]+)",                     # /file/d/FILE_ID
            r"[?&]id=([^&]+)",                      # ?id=FILE_ID or &id=FILE_ID
            r"/folders/([^/?#]+)",                  # /folders/FOLDER_ID
            r"/drive/folders/([^/?#]+)",            # /drive/folders/FOLDER_ID
            r"/embeddedfolderview\?id=([^&]+)",     # embeddedfolderview?id=FOLDER_ID
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _download_single_gdrive(self, url: str) -> None:
        file_id = self._extract_gdrive_id(url)
        if not file_id:
            raise ValueError("Invalid Google Drive URL or unable to extract file/folder ID")

        base_dir = Path("cloud") / "google_drive" / file_id
        base_dir.mkdir(parents=True, exist_ok=True)

        is_folder = any(p in url for p in [
            "/folders/",
            "/drive/folders/",
            "embeddedfolderview",
        ])

        if is_folder:
            folder_url = f"https://drive.google.com/drive/folders/{file_id}"
            subprocess.run(["gdown", "--folder", folder_url], cwd=base_dir, check=True)
        else:
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            subprocess.run(["gdown", download_url], cwd=base_dir, check=True)

    def _run_link_downloader(self, urls: List[str], download_func: Callable[[str], None]) -> None:
        total = len(urls)
        success_count = 0
        failure_count = 0

        for idx, url in enumerate(urls, start=1):
            print(f"[{idx}/{total}] Downloading: {url}")
            try:
                download_func(url)
                print("  ✓ Success")
                success_count += 1
            except Exception as e:
                print(f"  ✗ Failed: {e}")
                failure_count += 1

        print(f"\nDownload complete: {success_count} succeeded, {failure_count} failed.")

    def download_gdrive_links(self, urls: List[str]) -> None:
        """Download a list of Google Drive URLs (files or folders)."""
        if not urls:
            return
        self._run_link_downloader(urls, self._download_single_gdrive)


class ExternalLinksExtractor:
    """Extract external links from cached post content"""

    DEFAULT_URL_PATTERN = r'https?://[^\s<>"{}|\\^`\[\]]+'

    def __init__(self, cache: Cache, logger: Logger):
        self.cache = cache
        self.logger = logger

    def extract_links_from_artist(
        self,
        artist_id: str,
        match: Optional[str] = None,
        unique: bool = True,
        filter_func: Optional[Callable[[ExternalLink], bool]] = None
    ) -> List[ExternalLink]:
        """Extract links from an artist's cached posts

        Args:
            artist_id: Artist ID
            match: Optional regex pattern to filter URLs
            unique: Whether to return only unique URLs
            filter_func: Optional function to filter ExternalLink objects

        Returns:
            List of ExternalLink objects
        """
        posts = self.cache.load_posts(artist_id)
        links_dict = {}

        for post in posts:
            if post.content:
                post_links = self._extract_urls(post.content, match)
                for url in post_links:
                    if unique and url in links_dict:
                        continue

                    domain = self._extract_domain(url)
                    protocol = urlparse(url).scheme

                    link = ExternalLink(
                        url=url,
                        domain=domain,
                        protocol=protocol,
                        post_id=post.id,
                        artist_id=artist_id
                    )

                    if filter_func is None or filter_func(link):
                        links_dict[url] = link

        return list(links_dict.values())

    def get_link_statistics(
        self,
        links: List[ExternalLink]
    ) -> Dict:
        """Get statistics about extracted links"""
        domain_counts = {}
        protocol_counts = {}
        unique_posts = set()
        unique_artists = set()

        for link in links:
            domain_counts[link.domain] = domain_counts.get(link.domain, 0) + 1
            protocol_counts[link.protocol] = protocol_counts.get(link.protocol, 0) + 1
            unique_posts.add(link.post_id)
            unique_artists.add(link.artist_id)

        sorted_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)

        return {
            'total_links': len(links),
            'unique_domains': len(domain_counts),
            'unique_posts': len(unique_posts),
            'unique_artists': len(unique_artists),
            'top_domains': dict(sorted_domains[:10]),
            'protocols': protocol_counts
        }

    def _extract_urls(self, text: str, match: Optional[str] = None) -> List[str]:
        """Extract URLs from text using regex"""
        urls = re.findall(self.DEFAULT_URL_PATTERN, text)

        if match:
            try:
                pattern = re.compile(match, re.IGNORECASE)
                urls = [url for url in urls if pattern.search(url)]
            except re.error as e:
                self.logger.error(f"Invalid regex pattern '{match}': {e}")
                return []

        return urls

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return 'unknown'
