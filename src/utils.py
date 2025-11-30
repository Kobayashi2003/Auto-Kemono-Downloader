from typing import Any, List, Mapping, Sequence

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

    @staticmethod
    def sequence_contains_all(
        superset_items: Sequence[Mapping[str, Any]] | None,
        subset_items: Sequence[Mapping[str, Any]] | None,
        *,
        key_fields: Sequence[str] | None = None,
    ) -> bool:
        """Return True if superset_items contains all subset_items.

        "Contain" means: for every mapping in subset_items there exists at
        least one mapping in superset_items whose selected key/value pairs are
        a superset of the subset mapping's selected key/value pairs.

        The comparison is performed on the fields listed in ``key_fields``.
        If ``key_fields`` is None, all keys present in the remote mapping
        are used for comparison.
        """

        if not subset_items:
            # Nothing to check, treat as contained
            return True

        if not superset_items:
            return False

        for subset in subset_items:
            if not isinstance(subset, Mapping):
                continue

            # Determine which keys to compare for this item
            keys = key_fields or list(subset.keys())

            def is_match(candidate: Mapping[str, Any]) -> bool:
                for k in keys:
                    if k in subset and candidate.get(k) != subset[k]:
                        return False
                return True

            if not any(is_match(item) for item in superset_items if isinstance(item, Mapping)):
                return False

        return True
