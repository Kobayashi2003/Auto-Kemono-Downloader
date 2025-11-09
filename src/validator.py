import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from .formatter import Formatter
from .models import (
    ArtistFolderParams,
    FileParams,
    PostFolderParams,
    ValidationLevel,
    ValidationData,
    ValidationArtistData,
    ValidationPostData,
    ValidationFileData,
    ValidationConfig,
)


class Validator:
    """Three-level path conflict validator with ignore management

    Each level validates only its own uniqueness, assuming parent levels are valid.
    """

    def __init__(self, data_dir: str):
        """Initialize Validator with data directory"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.ignore_file = self.data_dir / "validation_ignore.json"

    # ==================== Public API ====================

    def validate_full_paths(
        self,
        validation_data: ValidationData,
        level: ValidationLevel = None,
    ) -> Tuple[List[tuple], int, Path]:
        """Validate paths with automatic ignore management

        Returns: (filtered_conflicts, filtered_count)
        """
        # Get download_dir from first artist
        download_dir = validation_data.artists[0].config.download_dir if validation_data.artists else ""

        # Perform validation
        all_conflicts = self._validate_full_paths(validation_data, level)

        # Load all ignores
        if not self.ignore_file.exists():
            all_data = {}
        else:
            try:
                with open(self.ignore_file, 'r', encoding='utf-8') as f:
                    all_data = json.load(f)
                    if not isinstance(all_data, dict):
                        all_data = {}
            except Exception:
                all_data = {}

        # Load ignores for each artist and filter conflicts
        artist_ignores = {}
        all_ignored_paths = []
        for artist_data in validation_data.artists:
            artist_data_dict = all_data.get(artist_data.id, {})
            ignored_relative = artist_data_dict.get('ignores', [])
            # Convert relative paths to absolute for filtering
            ignored_absolute = [str(Path(download_dir) / p) for p in ignored_relative]
            artist_ignores[artist_data.id] = ignored_relative
            all_ignored_paths.extend(ignored_absolute)

        # Filter conflicts
        original_count = len(all_conflicts)
        if all_ignored_paths:
            ignored_set = set(all_ignored_paths)
            filtered_conflicts = [(path, ids) for path, ids in all_conflicts if path not in ignored_set]
        else:
            filtered_conflicts = all_conflicts
        filtered_count = original_count - len(filtered_conflicts)

        # Group conflicts by artist
        artist_conflicts = defaultdict(list)
        for path, ids in filtered_conflicts:
            if ids:
                artist_id = ids[0].split(':')[0]
                artist_conflicts[artist_id].append((path, ids))

        # Update JSON for all validated artists
        for artist_data in validation_data.artists:
            artist_id = artist_data.id
            artist_conflict_list = artist_conflicts.get(artist_id, [])
            # Strip download_dir from conflict paths
            conflict_paths_relative = [
                self._strip_download_dir(path, download_dir)
                for path, _ in artist_conflict_list
            ]
            ignored_paths = artist_ignores.get(artist_id, [])

            # Get existing ignores and merge
            existing_data = all_data.get(artist_id, {})
            existing_ignores = existing_data.get('ignores', [])
            conflicts_set = set(conflict_paths_relative)
            merged_ignores = [path for path in existing_ignores if path in conflicts_set]
            for path in ignored_paths:
                if path not in merged_ignores:
                    merged_ignores.append(path)

            all_data[artist_id] = {
                "artist_id": artist_id,
                "artist_name": artist_data.name,
                "conflicts": conflict_paths_relative,
                "ignores": merged_ignores
            }

        # Save all data
        with open(self.ignore_file, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)

        return filtered_conflicts, filtered_count

    def get_ignore_file_path(self) -> str:
        return self.ignore_file

    def load_ignore_data(self) -> Dict:
        """Load validation ignore data for editing"""
        if not self.ignore_file.exists():
            return {}

        try:
            with open(self.ignore_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_ignore_data(self, data: Dict):
        """Save validation ignore data after editing"""
        with open(self.ignore_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ==================== Builder ====================

    @staticmethod
    def build_validation_data(artists_with_posts, global_config) -> ValidationData:
        """Build ValidationData from artists and their posts"""
        validation_artists = []

        # Helper lambda to get config value from object or dict
        get_config = lambda key: getattr(global_config, key) if hasattr(global_config, key) else global_config[key]

        for artist, posts in artists_with_posts:
            # Merge global config with artist-specific config
            artist_config = ValidationConfig(
                download_dir=get_config('download_dir'),
                artist_folder_template=artist.config.get('artist_folder_template', get_config('artist_folder_template')),
                post_folder_template=artist.config.get('post_folder_template', get_config('post_folder_template')),
                file_template=artist.config.get('file_template', get_config('file_template')),
                date_format=get_config('date_format'),
                rename_images_only=get_config('rename_images_only'),
                image_extensions=get_config('image_extensions'),
            )

            # Build posts data
            validation_posts = []
            for post in posts:
                # Collect files
                files = []
                if hasattr(post, 'file') and post.file:
                    files.append(ValidationFileData(name=post.file.get('name', ''), idx=0))
                if hasattr(post, 'attachments') and post.attachments:
                    for idx, attachment in enumerate(post.attachments, start=1 if (hasattr(post, 'file') and post.file) else 0):
                        files.append(ValidationFileData(name=attachment.get('name', ''), idx=idx))

                if files:
                    validation_posts.append(ValidationPostData(
                        id=post.id,
                        user=post.user,
                        service=post.service,
                        title=post.title,
                        published=post.published,
                        files=files,
                    ))

            if validation_posts:
                validation_artists.append(ValidationArtistData(
                    id=artist.id,
                    service=artist.service,
                    name=artist.name,
                    alias=artist.alias,
                    user_id=artist.user_id,
                    last_date=artist.last_date or "",
                    posts=validation_posts,
                    config=artist_config,
                ))

        return ValidationData(artists=validation_artists)

    # ==================== Simple Validators (for testing) ====================

    @staticmethod
    def validate_artist_folders(artist_params_list: List[ArtistFolderParams], template: str) -> List[tuple]:
        """Validate artist folder uniqueness"""
        path_to_indices = defaultdict(list)

        for idx, params in enumerate(artist_params_list):
            path = Formatter.format_artist_folder(params, template)
            path_to_indices[str(path)].append(idx)

        conflicts = [
            (path, indices)
            for path, indices in path_to_indices.items()
            if len(indices) > 1
        ]

        conflicts.sort(key=lambda x: len(x[1]), reverse=True)
        return conflicts

    @staticmethod
    def validate_post_folders(post_params_list: List[PostFolderParams], template: str, date_format: str) -> List[tuple]:
        """Validate post folder uniqueness"""
        path_to_indices = defaultdict(list)

        for idx, params in enumerate(post_params_list):
            path = Formatter.format_post_folder(params, template, date_format)
            path_to_indices[str(path)].append(idx)

        conflicts = [
            (path, indices)
            for path, indices in path_to_indices.items()
            if len(indices) > 1
        ]

        conflicts.sort(key=lambda x: len(x[1]), reverse=True)
        return conflicts

    @staticmethod
    def validate_file_names(file_params_list: List[FileParams], template: str) -> List[tuple]:
        """Validate file name uniqueness"""
        name_to_indices = defaultdict(list)

        for idx, params in enumerate(file_params_list):
            filename = Formatter.format_file_name(params, template)
            name_to_indices[filename].append(idx)

        conflicts = [
            (filename, indices)
            for filename, indices in name_to_indices.items()
            if len(indices) > 1
        ]

        conflicts.sort(key=lambda x: len(x[1]), reverse=True)
        return conflicts

    # ==================== Internal Validation Logic ====================

    @staticmethod
    def _validate_artist_level(validation_data: ValidationData) -> List[tuple]:
        """Validate artist folder uniqueness"""
        artist_path_to_ids = defaultdict(list)

        for artist in validation_data.artists:
            artist_params = ArtistFolderParams(
                service=artist.service,
                name=artist.name,
                alias=artist.alias,
                user_id=artist.user_id,
                last_date=artist.last_date,
            )
            artist_folder = Formatter.format_artist_folder(
                artist_params, artist.config.artist_folder_template
            )
            artist_path = Path(artist.config.download_dir) / artist_folder
            artist_path_to_ids[str(artist_path)].append(artist.id)

        return [
            (path, artist_ids)
            for path, artist_ids in artist_path_to_ids.items()
            if len(artist_ids) > 1
        ]

    @staticmethod
    def _validate_post_level(validation_data: ValidationData) -> List[tuple]:
        """Validate post folder uniqueness"""
        post_path_to_ids = defaultdict(list)

        for artist in validation_data.artists:
            artist_params = ArtistFolderParams(
                service=artist.service,
                name=artist.name,
                alias=artist.alias,
                user_id=artist.user_id,
                last_date=artist.last_date,
            )
            artist_folder = Formatter.format_artist_folder(
                artist_params, artist.config.artist_folder_template
            )

            for post in artist.posts:
                post_params = PostFolderParams(
                    id=post.id,
                    user=post.user,
                    service=post.service,
                    title=post.title,
                    published=post.published,
                )
                post_folder = Formatter.format_post_folder(
                    post_params, artist.config.post_folder_template, artist.config.date_format
                )
                post_path = Path(artist.config.download_dir) / artist_folder / post_folder
                post_path_to_ids[str(post_path)].append(f"{artist.id}:{post.id}")

        return [
            (path, post_ids)
            for path, post_ids in post_path_to_ids.items()
            if len(post_ids) > 1
        ]

    @staticmethod
    def _validate_file_level(validation_data: ValidationData) -> List[tuple]:
        """Validate file path uniqueness"""
        file_path_to_info = defaultdict(list)

        for artist in validation_data.artists:
            artist_params = ArtistFolderParams(
                service=artist.service,
                name=artist.name,
                alias=artist.alias,
                user_id=artist.user_id,
                last_date=artist.last_date,
            )
            artist_folder = Formatter.format_artist_folder(
                artist_params, artist.config.artist_folder_template
            )

            for post in artist.posts:
                post_params = PostFolderParams(
                    id=post.id,
                    user=post.user,
                    service=post.service,
                    title=post.title,
                    published=post.published,
                )
                post_folder = Formatter.format_post_folder(
                    post_params, artist.config.post_folder_template, artist.config.date_format
                )

                # Format all file names at once
                file_names = [file.name for file in post.files]
                formatted_names = Formatter.format_files_names(
                    file_names,
                    artist.config.file_template,
                    artist.config.rename_images_only,
                    artist.config.image_extensions,
                )

                for file, filename in zip(post.files, formatted_names):
                    full_path = Path(artist.config.download_dir) / artist_folder / post_folder / filename
                    file_info = f"{artist.id}:{post.id}:{file.name}"
                    file_path_to_info[str(full_path)].append(file_info)

        return [
            (path, file_infos)
            for path, file_infos in file_path_to_info.items()
            if len(file_infos) > 1
        ]

    @staticmethod
    def _validate_full_paths(validation_data: ValidationData, level: ValidationLevel = None) -> List[tuple]:
        """Perform path validation"""
        if level is None:
            level = ValidationLevel()

        conflicts = []
        if level.artist_unique:
            conflicts.extend(Validator._validate_artist_level(validation_data))
        if level.post_unique:
            conflicts.extend(Validator._validate_post_level(validation_data))
        if level.file_unique:
            conflicts.extend(Validator._validate_file_level(validation_data))

        conflicts.sort(key=lambda x: len(x[1]), reverse=True)
        return conflicts

    @staticmethod
    def _strip_download_dir(path: str, download_dir: str) -> str:
        """Remove download_dir prefix from path"""
        path_obj = Path(path)
        download_dir_obj = Path(download_dir)
        try:
            relative = path_obj.relative_to(download_dir_obj)
            return str(relative)
        except ValueError:
            return path
