import json
import threading
from pathlib import Path
from typing import List, Optional

from .models import Artist, Config, HistoryRecord


class Storage:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.artists_dir = self.data_dir / "artists"
        self.artists_file = self.data_dir / "artists.json"
        self.config_file = self.data_dir / "config.json"
        self.history_file = self.data_dir / "history.json"
        self.lock = threading.Lock()
        self._ensure_files()

    def _ensure_files(self):
        if not self.artists_file.exists():
            self.artists_file.write_text("[]", encoding='utf-8')
        if not self.config_file.exists():
            self.config_file.write_text("{}", encoding='utf-8')
        if not self.history_file.exists():
            self.history_file.write_text("[]", encoding='utf-8')

    def load_config(self) -> Config:
        with self.lock:
            data = json.loads(self.config_file.read_text(encoding='utf-8'))
            if not data:
                return Config()

            if 'image_extensions' in data and isinstance(data['image_extensions'], list):
                data['image_extensions'] = set(data['image_extensions'])

            return Config(**data)

    def save_config(self, config: Config):
        with self.lock:
            data = config.__dict__.copy()
            if 'image_extensions' in data and isinstance(data['image_extensions'], set):
                data['image_extensions'] = list(data['image_extensions'])
            self.config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def get_artists(self) -> List[Artist]:
        with self.lock:
            # Load base list from artists.json
            data = json.loads(self.artists_file.read_text(encoding='utf-8'))
            artists = [Artist(**item) for item in data]

            # If there is an artists/ directory, recursively load all JSON files.
            # artists.json has the highest priority. For IDs not defined there,
            # the first occurrence in artists/ (by rglob order) wins.
            if self.artists_dir.exists() and self.artists_dir.is_dir():
                existing_ids = {a.id for a in artists}

                for json_path in self.artists_dir.rglob('*.json'):
                    try:
                        content = json.loads(json_path.read_text(encoding='utf-8'))
                    except Exception:
                        continue

                    if isinstance(content, dict):
                        items = [content]
                    elif isinstance(content, list):
                        items = [item for item in content if isinstance(item, dict)]
                    else:
                        continue

                    for item in items:
                        artist_id = item.get('id')
                        if not artist_id or artist_id in existing_ids:
                            continue
                        artists.append(Artist(**item))
                        existing_ids.add(artist_id)

            return artists

    def get_artist(self, artist_id: str) -> Optional[Artist]:
        artists = self.get_artists()
        return next((a for a in artists if a.id == artist_id), None)

    def save_artist(self, artist: Artist):
        with self.lock:
            # 1) Try update in artists.json (highest priority)
            data = json.loads(self.artists_file.read_text(encoding='utf-8'))
            artists = [Artist(**item) for item in data]

            for i, a in enumerate(artists):
                if a.id == artist.id:
                    artists[i] = artist
                    data = [x.__dict__ for x in artists]
                    self.artists_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                    return

            # 2) Not in artists.json -> search artists/ recursively
            if self.artists_dir.exists() and self.artists_dir.is_dir():
                for json_path in self.artists_dir.rglob('*.json'):
                    try:
                        content = json.loads(json_path.read_text(encoding='utf-8'))
                    except Exception:
                        continue

                    changed = False
                    if isinstance(content, dict):
                        if content.get('id') == artist.id:
                            content = artist.__dict__
                            changed = True
                    elif isinstance(content, list):
                        for idx, item in enumerate(content):
                            if isinstance(item, dict) and item.get('id') == artist.id:
                                content[idx] = artist.__dict__
                                changed = True
                                break

                    if changed:
                        json_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding='utf-8')
                        return

            # 3) Not found anywhere -> append to artists.json
            artists.append(artist)
            data = [x.__dict__ for x in artists]
            self.artists_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def remove_artist(self, artist_id: str):
        with self.lock:
            # 1) Try remove from artists.json
            data = json.loads(self.artists_file.read_text(encoding='utf-8'))
            artists = [Artist(**item) for item in data]

            new_artists = [a for a in artists if a.id != artist_id]
            if len(new_artists) != len(artists):
                data = [x.__dict__ for x in new_artists]
                self.artists_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                return

            # 2) Not in artists.json -> search artists/ recursively
            if self.artists_dir.exists() and self.artists_dir.is_dir():
                for json_path in self.artists_dir.rglob('*.json'):
                    try:
                        content = json.loads(json_path.read_text(encoding='utf-8'))
                    except Exception:
                        continue

                    changed = False
                    if isinstance(content, dict):
                        if content.get('id') == artist_id:
                            content = None
                            changed = True
                    elif isinstance(content, list):
                        original_len = len(content)
                        content = [item for item in content if not (isinstance(item, dict) and item.get('id') == artist_id)]
                        changed = len(content) != original_len

                    if changed:
                        # If the file contained only this artist as a dict, remove file
                        if content is None:
                            json_path.unlink(missing_ok=True)
                        else:
                            json_path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding='utf-8')
                        return

    # ==================== History ====================

    def add_history(self, command: str, success: bool = True, artist_id: str = None, params: dict = None, note: str = ""):
        """Add a command to history with optional artist_id and parameters"""
        with self.lock:
            data = json.loads(self.history_file.read_text(encoding='utf-8'))
            record = HistoryRecord(
                command=command,
                success=success,
                artist_id=artist_id,
                params=params or {},
                note=note
            )
            data.append(record.__dict__)
            self.history_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def get_history(self, limit: int = 10) -> List[HistoryRecord]:
        """Get recent command history, newest first"""
        with self.lock:
            data = json.loads(self.history_file.read_text(encoding='utf-8'))
            records = [HistoryRecord(**item) for item in data]
            # Return newest first
            return records[-limit:][::-1] if len(records) > 0 else []

    def clear_history(self):
        """Clear all history"""
        with self.lock:
            self.history_file.write_text("[]", encoding='utf-8')
