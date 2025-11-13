import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import Post, Profile


class Cache:
    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.lock = threading.Lock()

    def _profile_path(self, artist_id: str) -> Path:
        return self.cache_dir / f"{artist_id}_profile.json"

    def _posts_path(self, artist_id: str) -> Path:
        return self.cache_dir / f"{artist_id}_posts.json"

    def save_profile(self, artist_id: str, profile_data: Dict):
        with self.lock:
            # Filter only needed fields
            filtered_data = {
                'id': profile_data.get('id'),
                'name': profile_data.get('name'),
                'service': profile_data.get('service'),
                'indexed': profile_data.get('indexed'),
                'updated': profile_data.get('updated'),
                'public_id': profile_data.get('public_id'),
                'relation_id': profile_data.get('relation_id'),
                'post_count': profile_data.get('post_count', 0),
                'dm_count': profile_data.get('dm_count', 0),
                'share_count': profile_data.get('share_count', 0),
                'chat_count': profile_data.get('chat_count', 0),
            }
            profile = Profile(**filtered_data)
            profile.cached_at = datetime.now().isoformat()

            path = self._profile_path(artist_id)
            path.write_text(json.dumps(profile.__dict__, indent=2, ensure_ascii=False), encoding='utf-8')

    def load_profile(self, artist_id: str) -> Optional[Profile]:
        with self.lock:
            path = self._profile_path(artist_id)
            if not path.exists():
                return None

            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                return Profile(**data)
            except Exception:
                return None

    def save_posts(self, artist_id: str, posts: List[Post]):
        with self.lock:
            path = self._posts_path(artist_id)
            data = [post.__dict__ for post in posts]
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def load_posts(self, artist_id: str) -> List[Post]:
        with self.lock:
            path = self._posts_path(artist_id)
            if not path.exists():
                return []

            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                return [Post(**item) for item in data]
            except Exception:
                return []

    def update_post(self, artist_id: str, post_id: str, done: bool, failed_files: List[str] = None, content: str = None):
        posts = self.load_posts(artist_id)
        for post in posts:
            if post.id == post_id:
                post.done = done
                if failed_files is not None:
                    post.failed_files = failed_files
                if content is not None:
                    post.content = content
                break
        self.save_posts(artist_id, posts)

    def reset_post(self, artist_id: str, post_id: str):
        self.update_post(artist_id, post_id, done=False, failed_files=[])

    def stats(self, artist_id: str) -> Dict:
        posts = self.load_posts(artist_id)
        total = len(posts)
        done = sum(1 for p in posts if p.done)
        failed = sum(1 for p in posts if p.failed_files)

        return {
            'total': total,
            'done': done,
            'pending': total - done,
            'failed': failed
        }

    def has_new(self, artist_id: str, current_count: int) -> bool:
        profile = self.load_profile(artist_id)
        if not profile:
            return True
        return current_count > profile.post_count

    def get_undone(self, artist_id: str) -> List[Post]:
        """Get undone posts (not done or has failed files)"""
        posts = self.load_posts(artist_id)
        return [post for post in posts if not post.done or post.failed_files]

    def mark_old_done(self, artist_id: str, before_date: str):
        posts = self.load_posts(artist_id)
        for post in posts:
            if post.published <= before_date:
                post.done = True
        self.save_posts(artist_id, posts)

    def reset_after_date(self, artist_id: str, after_date: str = None) -> int:
        """Reset posts to undone

        If after_date is None, reset all posts.
        Otherwise, reset posts after the specified date.
        """
        posts = self.load_posts(artist_id)
        if not posts:
            return 0

        reset_count = 0
        for post in posts:
            # Skip if published is None
            if not post.published:
                continue

            # If no date specified, reset all done posts
            if not after_date:
                if post.done:
                    post.done = False
                    post.failed_files = []
                    reset_count += 1
            # Otherwise, reset posts after the date
            elif post.published > after_date and post.done:
                post.done = False
                post.failed_files = []
                reset_count += 1

        if reset_count > 0:
            self.save_posts(artist_id, posts)

        return reset_count

    def deduplicate_posts(self, artist_id: str) -> int:
        """Remove duplicate posts by ID, keeping the first occurrence

        Returns:
            Number of duplicates removed
        """
        posts = self.load_posts(artist_id)
        if not posts:
            return 0

        seen_ids = set()
        unique_posts = []
        duplicate_count = 0

        for post in posts:
            if post.id not in seen_ids:
                seen_ids.add(post.id)
                unique_posts.append(post)
            else:
                duplicate_count += 1

        if duplicate_count > 0:
            self.save_posts(artist_id, unique_posts)

        return duplicate_count
