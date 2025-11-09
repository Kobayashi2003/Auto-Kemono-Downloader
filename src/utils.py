from typing import Any, List

from .models import Artist, Config, Post


class Utils:
    """Common utility functions"""

    @staticmethod
    def get_config_value(artist: Artist, config: Config, key: str, default=None) -> Any:
        """Get config value with artist-level override"""
        return artist.config.get(key, getattr(config, key, default))

    @staticmethod
    def extract_files(post: Post) -> List[dict]:
        """Extract file URLs from post"""
        files = []

        if post.file:
            path = post.file.get('path', '')
            if path and not path.startswith('http'):
                path = f"https://kemono.cr{path}"
            files.append({'url': path, 'name': post.file.get('name', 'file')})

        if post.attachments:
            for att in post.attachments:
                path = att.get('path', '')
                if path and not path.startswith('http'):
                    path = f"https://kemono.cr{path}"
                files.append({'url': path, 'name': att.get('name', 'attachment')})

        return [f for f in files if f['url']]
