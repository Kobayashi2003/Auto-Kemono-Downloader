from collections import defaultdict
from pathlib import Path

from .cache import Cache
from .formatter import Formatter
from .models import (
    Artist,
    ArtistFolderParams,
    MigrationConfig,
    MigrationPlan,
    MigrationResult,
    MigrationType,
    PostFolderParams,
)
from .storage import Storage


class Migrator:
    """Template migration tool"""

    def __init__(self, storage: Storage, cache: Cache):
        self.storage = storage
        self.cache = cache

    def migrate_posts(self, artist: Artist, old_config: MigrationConfig, new_config: MigrationConfig) -> MigrationPlan:
        """Migrate post folders with comprehensive conflict detection"""
        posts = self.cache.load_posts(artist.id)
        if not posts:
            return MigrationPlan.empty(MigrationType.POST)

        # Step 1: Build mappings for existing posts
        post_mappings = {}  # post_id → (old_path, new_path)
        old_path_to_posts = defaultdict(list)  # old_path_str → [post_ids]
        new_path_to_posts = defaultdict(list)  # new_path_str → [post_ids]
        skipped = []

        for post in posts:
            old_path = self._get_post_path(artist, post, old_config)
            new_path = self._get_post_path(artist, post, new_config)

            # Only process posts with existing old paths
            if not old_path.exists():
                skipped.append((post.id, "Source not found"))
                continue

            post_mappings[post.id] = (old_path, new_path)
            old_path_to_posts[str(old_path)].append(post.id)
            new_path_to_posts[str(new_path)].append(post.id)

        if not post_mappings:
            return MigrationPlan(
                migration_type=MigrationType.POST,
                total_items=len(posts),
                mappings=[],
                conflicts=[],
                skipped=skipped,
                success_count=0,
                conflict_count=0,
                skipped_count=len(skipped)
            )

        # Step 2: Detect conflicts
        all_conflicts = []
        conflict_posts = set()

        # 2.1 Detect old path conflicts (multiple posts → same old path)
        old_path_conflicts = [
            (old_path, post_ids)
            for old_path, post_ids in old_path_to_posts.items()
            if len(post_ids) > 1
        ]
        for old_path, post_ids in old_path_conflicts:
            all_conflicts.append((old_path, post_ids))
            conflict_posts.update(post_ids)

        # 2.2 Detect new path conflicts (multiple posts → same new path)
        new_path_conflicts = [
            (new_path, post_ids)
            for new_path, post_ids in new_path_to_posts.items()
            if len(post_ids) > 1
        ]
        for new_path, post_ids in new_path_conflicts:
            all_conflicts.append((new_path, post_ids))
            conflict_posts.update(post_ids)

        # Step 3: Generate valid mappings (exclude conflicts)
        mappings = []

        for post_id, (old_path, new_path) in post_mappings.items():
            if post_id in conflict_posts:
                # Determine skip reason
                old_path_str = str(old_path)
                new_path_str = str(new_path)

                if old_path_str in dict(old_path_conflicts):
                    count = len(old_path_to_posts[old_path_str])
                    skipped.append((post_id, f"Old path conflict ({count} posts → 1 folder)"))
                elif new_path_str in dict(new_path_conflicts):
                    count = len(new_path_to_posts[new_path_str])
                    skipped.append((post_id, f"New path conflict ({count} posts → 1 path)"))
                else:
                    skipped.append((post_id, "Path conflict"))
                continue

            if old_path == new_path:
                skipped.append((post_id, "Same path"))
                continue

            if new_path.exists():
                skipped.append((post_id, "Target exists"))
                continue

            mappings.append((str(old_path), str(new_path), post_id))

        return MigrationPlan(
            migration_type=MigrationType.POST,
            total_items=len(posts),
            mappings=mappings,
            conflicts=all_conflicts,
            skipped=skipped,
            success_count=len(mappings),
            conflict_count=len(conflict_posts),
            skipped_count=len(skipped)
        )

    def migrate_files(self, artist: Artist, old_config: MigrationConfig, new_config: MigrationConfig) -> MigrationPlan:
        """Migrate files within posts with comprehensive conflict detection"""
        posts = self.cache.load_posts(artist.id)
        if not posts:
            return MigrationPlan.empty(MigrationType.FILE)

        # Step 1: Filter posts with existing post paths
        existing_posts = []
        for post in posts:
            post_path = self._get_post_path(artist, post, old_config)
            if post_path.exists():
                existing_posts.append(post)

        if not existing_posts:
            return MigrationPlan.empty(MigrationType.FILE)

        # Step 2: Build file mappings
        file_mappings = {}  # file_key → (old_path, new_path)
        old_path_to_files = defaultdict(list)  # old_path_str → [file_keys]
        new_path_to_files = defaultdict(list)  # new_path_str → [file_keys]
        skipped = []
        total_files = 0

        for post in existing_posts:
            # Collect files
            files = []
            if post.file:
                files.append(post.file)
            if post.attachments:
                files.extend(post.attachments)

            # Format file names using batch API
            file_names = [f.get('name', '') for f in files]
            old_formatted = Formatter.format_files_names(
                file_names, old_config.file_template,
                old_config.rename_images_only, old_config.image_extensions
            )
            new_formatted = Formatter.format_files_names(
                file_names, new_config.file_template,
                new_config.rename_images_only, new_config.image_extensions
            )

            old_post_path = self._get_post_path(artist, post, old_config)
            new_post_path = self._get_post_path(artist, post, new_config)

            for file_dict, old_filename, new_filename in zip(files, old_formatted, new_formatted):
                total_files += 1
                original_name = file_dict.get('name', '')
                file_key = f"{post.id}:{original_name}"

                old_file_path = old_post_path / old_filename
                new_file_path = new_post_path / new_filename

                if not old_file_path.exists():
                    skipped.append((file_key, "Source not found"))
                    continue

                file_mappings[file_key] = (old_file_path, new_file_path)
                old_path_to_files[str(old_file_path)].append(file_key)
                new_path_to_files[str(new_file_path)].append(file_key)

        if not file_mappings:
            return MigrationPlan(
                migration_type=MigrationType.FILE,
                total_items=total_files,
                mappings=[],
                conflicts=[],
                skipped=skipped,
                success_count=0,
                conflict_count=0,
                skipped_count=len(skipped)
            )

        # Step 3: Detect conflicts
        all_conflicts = []
        conflict_files = set()

        # 3.1 Detect old path conflicts (multiple files → same old path)
        old_path_conflicts = [
            (old_path, file_keys)
            for old_path, file_keys in old_path_to_files.items()
            if len(file_keys) > 1
        ]
        for old_path, file_keys in old_path_conflicts:
            all_conflicts.append((old_path, file_keys))
            conflict_files.update(file_keys)

        # 3.2 Detect new path conflicts (multiple files → same new path)
        new_path_conflicts = [
            (new_path, file_keys)
            for new_path, file_keys in new_path_to_files.items()
            if len(file_keys) > 1
        ]
        for new_path, file_keys in new_path_conflicts:
            all_conflicts.append((new_path, file_keys))
            conflict_files.update(file_keys)

        # Step 4: Generate valid mappings (exclude conflicts)
        mappings = []

        for file_key, (old_path, new_path) in file_mappings.items():
            if file_key in conflict_files:
                # Determine skip reason
                old_path_str = str(old_path)
                new_path_str = str(new_path)

                if old_path_str in dict(old_path_conflicts):
                    count = len(old_path_to_files[old_path_str])
                    skipped.append((file_key, f"Old path conflict ({count} files → 1 path)"))
                elif new_path_str in dict(new_path_conflicts):
                    count = len(new_path_to_files[new_path_str])
                    skipped.append((file_key, f"New path conflict ({count} files → 1 path)"))
                else:
                    skipped.append((file_key, "Path conflict"))
                continue

            if old_path == new_path:
                skipped.append((file_key, "Same path"))
                continue

            if new_path.exists():
                skipped.append((file_key, "Target exists"))
                continue

            mappings.append((str(old_path), str(new_path), file_key))

        return MigrationPlan(
            migration_type=MigrationType.FILE,
            total_items=total_files,
            mappings=mappings,
            conflicts=all_conflicts,
            skipped=skipped,
            success_count=len(mappings),
            conflict_count=len(conflict_files),
            skipped_count=len(skipped)
        )

    def execute_migration(self, plan: MigrationPlan) -> MigrationResult:
        """Execute migration"""
        results = MigrationResult(
            migration_type=plan.migration_type,
            total=len(plan.mappings),
            success=0,
            failed=[]
        )

        for old_path, new_path, item_id in plan.mappings:
            try:
                old_path_obj = Path(old_path)
                new_path_obj = Path(new_path)

                new_path_obj.parent.mkdir(parents=True, exist_ok=True)
                old_path_obj.rename(new_path_obj)
                results.success += 1

            except Exception as e:
                results.failed.append((old_path, new_path, item_id, str(e)))

        return results

    def _get_post_path(self, artist: Artist, post, config: MigrationConfig) -> Path:
        """Get post folder path from MigrationConfig"""
        artist_params = ArtistFolderParams(
            service=artist.service,
            name=artist.name,
            alias=artist.alias,
            user_id=artist.user_id,
            last_date=artist.last_date or "",
        )

        post_params = PostFolderParams(
            id=post.id,
            user=post.user,
            service=post.service,
            title=post.title,
            published=post.published,
        )

        artist_folder = Formatter.format_artist_folder(artist_params, config.artist_folder_template)
        post_folder = Formatter.format_post_folder(post_params, config.post_folder_template, config.date_format)

        return Path(config.download_dir) / artist_folder / post_folder
