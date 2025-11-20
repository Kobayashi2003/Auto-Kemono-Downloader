import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .cache import Cache
from .logger import Logger
from .models import ExternalLink


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
        unique: bool = True
    ) -> List[ExternalLink]:
        """Extract links from an artist's cached posts

        Args:
            artist_id: Artist ID
            match: Optional regex pattern to filter URLs
            unique: Whether to return only unique URLs

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
