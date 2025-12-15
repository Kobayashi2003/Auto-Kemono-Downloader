import threading
from functools import reduce
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

from .api import API
from .cache import Cache
from .formatter import Formatter
from .logger import Logger
from .models import Artist, ArtistFolderParams, Config, DownloadArtistResult, DownloadPostResult, DownloadPostsResult, FileParams, NO_CONTENT_MARKER, Post, PostFolderParams
from .notifier import Notifier
from .storage import Storage
from .utils import Utils


class Downloader:
    def __init__(self, config: Config, logger: Logger, storage: Storage, cache: Cache, api: API, notifier: Optional[Notifier] = None):
        self.config = config
        self.logger = logger
        self.storage = storage
        self.cache = cache
        self.api = api
        self.notifier = notifier or Notifier(enabled=False)  # Default: no notifications
        self._stop_flag = threading.Event()  # Stop signal for graceful shutdown

    def stop(self):
        """Stop all download operations"""
        self._stop_flag.set()
        self.api.stop()  # Cancel all HTTP requests

    def resume(self):
        """Resume download operations after stop"""
        self._stop_flag.clear()
        self.api.resume()

    def download_artist(self, artist: Artist, from_date: Optional[str] = None, until_date: Optional[str] = None, manual: bool = False) -> DownloadArtistResult:

        try:
            # Check stop flag
            if self._stop_flag.is_set():
                return DownloadArtistResult.skipped(artist.id)

            # Skip if artist is marked as completed or ignore
            if artist.completed or artist.ignore:
                self.logger.downloader_artist_skipped(
                    artist=artist.display_name(),
                    status='completed' if artist.completed else 'ignored'
                )
                return DownloadArtistResult.skipped(artist.id)

            # Update cache if there are new posts
            self.update_posts_basic(artist)

            # Determine which posts to process
            if from_date or until_date:
                # Date range mode: process ALL posts in range (ignore done status)
                all_posts = self.cache.load_posts(artist.id)
                posts_to_process = [
                    post for post in all_posts
                    if (not from_date or post.published > from_date)
                    and (not until_date or post.published <= until_date)
                ]
                no_posts_msg = "No posts in date range"
            else:
                # Normal mode: only process undone posts
                posts_to_process = self.cache.get_undone(artist.id)
                no_posts_msg = "No posts to download"

            # Process posts or log if none
            if posts_to_process:
                posts_result = self.download_posts(artist, posts_to_process)
            else:
                self.logger.downloader_no_posts(
                    artist=artist.display_name(),
                    mode='range' if (from_date or until_date) else 'normal',
                    reason=no_posts_msg
                )
                posts_result = DownloadPostsResult.empty()

            # Update last_date after processing (only increase, never decrease)
            new_last_date = self._calculate_new_last_date(artist)
            if new_last_date and new_last_date > (artist.last_date or ""):
                artist.last_date = new_last_date
                self.storage.save_artist(artist)
                self.logger.downloader_last_date_updated(
                    artist=artist.display_name(), last_date=new_last_date
                )

            if posts_result.posts_downloaded > 0:
                self.logger.downloader_posts_downloaded(
                    artist=artist.display_name(), count=posts_result.posts_downloaded
                )

            return DownloadArtistResult(
                artist_id=artist.id,
                success=posts_result.success,
                posts_downloaded=posts_result.posts_downloaded,
                posts_failed=posts_result.posts_failed,
                failed_posts=posts_result.failed_posts
            )

        except Exception as e:
            self.logger.downloader_artist_failed(artist=artist.display_name(), error=str(e), level='error')
            return DownloadArtistResult.failed(artist.id)

    def download_posts(self, artist: Artist, posts: List[Post]) -> DownloadPostsResult:
        """Download multiple posts concurrently"""
        self.logger.downloader_processing_posts(artist=artist.display_name(), count=len(posts))
        self.notifier.notify_artist_start(artist.display_name(), len(posts))

        posts_downloaded = 0
        failed_post_results = []
        lock = threading.Lock()
        save_content = Utils.get_config_value(artist, self.config, 'save_content')

        def process_post(idx_post):
            idx, post = idx_post
            try:
                # Check stop flag
                if self._stop_flag.is_set():
                    return (False, DownloadPostResult.failed(artist.service, post.id))

                # Fetch full post if file info or content is missing
                needs_files = not post.file and not post.attachments
                needs_content = save_content and post.content == ""

                if needs_files or needs_content:
                    full_post_response = self.api.get_post_until_success(artist.service, artist.user_id, post.id)
                    full_post = full_post_response['post']

                    if needs_files:
                        post.file = full_post.get('file')
                        post.attachments = full_post.get('attachments', [])

                    if needs_content:
                        fetched_content = full_post.get('content', '')
                        post.content = fetched_content if fetched_content else NO_CONTENT_MARKER

                files = Utils.extract_files(post)
                file_count = len(files)

                self.logger.downloader_post_processing(
                    index=idx, total=len(posts), title=post.title[:60], files=file_count
                )

                post_result = self.download_post(artist, post)

                if post_result.success:
                    post.done = True
                    post.failed_files = []
                    content_to_save = post.content if post.content != "" else None
                    self.cache.update_post(artist.id, post.id, True, [], content_to_save)
                    if file_count > 0:
                        self.logger.downloader_post_success(
                            post_id=post.id, downloaded=post_result.files_downloaded, total=file_count
                        )
                    return (True, post_result)
                else:
                    self.logger.downloader_post_failed(
                        post_id=post.id, failed=post_result.files_failed, total=file_count, level='warning'
                    )
                    return (False, post_result)

            except Exception as e:
                self.logger.downloader_post_error(post_id=post.id, error=str(e), level='error')
                return (False, DownloadPostResult.failed(artist.service, post.id))

        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_posts) as executor:
            futures = {executor.submit(process_post, (idx, post)): post
                      for idx, post in enumerate(posts, 1)}

            for future in as_completed(futures):
                success, result = future.result()
                with lock:
                    if success:
                        posts_downloaded += 1
                    else:
                        failed_post_results.append(result)

        self.logger.downloader_artist_completed(
            artist=artist.display_name(), succeeded=posts_downloaded, failed=len(failed_post_results)
        )
        self.notifier.notify_artist_complete(artist.display_name(), posts_downloaded, len(failed_post_results))

        return DownloadPostsResult(
            success=not failed_post_results,
            posts_downloaded=posts_downloaded,
            posts_failed=len(failed_post_results),
            failed_posts=failed_post_results
        )

    def download_post(self, artist: Artist, post: Post) -> DownloadPostResult:
        # Get config values with artist-level override
        download_dir = Utils.get_config_value(artist, self.config, 'download_dir')
        artist_folder_template = Utils.get_config_value(artist, self.config, 'artist_folder_template')
        post_folder_template = Utils.get_config_value(artist, self.config, 'post_folder_template')
        file_template = Utils.get_config_value(artist, self.config, 'file_template')
        date_format = Utils.get_config_value(artist, self.config, 'date_format')
        rename_images_only = Utils.get_config_value(artist, self.config, 'rename_images_only')
        image_extensions = self.config.image_extensions  # Global only
        save_content = Utils.get_config_value(artist, self.config, 'save_content')
        save_empty_posts = Utils.get_config_value(artist, self.config, 'save_empty_posts')

        files = Utils.extract_files(post)

        # Skip posts without files unless configured to save them
        if not files and not save_empty_posts and not save_content:
            return DownloadPostResult.empty(artist.service, post.id)

        # Build artist folder params
        artist_params = ArtistFolderParams(
            service=artist.service,
            name=artist.name,
            alias=artist.alias,
            user_id=artist.user_id,
            last_date=artist.last_date or ""
        )

        # Build post folder params
        post_params = PostFolderParams(
            id=post.id,
            user=post.user,
            service=post.service,
            title=post.title,
            published=post.published
        )

        # Format paths
        artist_folder = Formatter.format_artist_folder(artist_params, artist_folder_template)
        post_folder = Formatter.format_post_folder(post_params, post_folder_template, date_format)
        save_dir = Path(download_dir) / artist_folder / post_folder
        save_dir.mkdir(parents=True, exist_ok=True)

        # Save content if available (content should already be fetched in download_posts)
        # Skip if NO_CONTENT_MARKER or empty
        if save_content and post.content and post.content != NO_CONTENT_MARKER:
            (save_dir / "content.txt").write_text(post.content, encoding='utf-8', errors='ignore')

        # If no files, return early after saving content
        if not files:
            return DownloadPostResult.empty(artist.service, post.id)

        # Format all file names at once
        original_names = [file['name'] for file in files]
        formatted_names = Formatter.format_files_names(
            original_names, file_template, rename_images_only, image_extensions
        )

        # Download files concurrently
        success_count = 0
        failed_files = []
        lock = threading.Lock()

        def download_file(file_info):
            file, file_name = file_info
            try:
                # Check stop flag
                if self._stop_flag.is_set():
                    return (False, file_name)

                save_path = save_dir / file_name
                self.api.download_file_until_success(
                    file['url'],
                    str(save_path),
                    on_start=self.notifier.on_download_start,
                    on_progress=self.notifier.on_download_progress,
                    on_complete=self.notifier.on_download_complete
                )
                self.logger.downloader_file_success(file=file_name)
                return (True, file_name)
            except Exception as e:
                self.logger.downloader_file_failed(file=file.get("name", "unknown"), error=str(e), level='error')
                return (False, file_name)

        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_files) as executor:
            futures = {executor.submit(download_file, (file, file_name)): file_name
                      for file, file_name in zip(files, formatted_names)}

            for future in as_completed(futures):
                success, file_name = future.result()
                with lock:
                    if success:
                        success_count += 1
                    else:
                        failed_files.append(file_name)

        all_success = not failed_files
        if not all_success:
            self.cache.update_post(artist.id, post.id, False, failed_files)

        return DownloadPostResult(
            service=artist.service,
            post_id=post.id,
            success=all_success,
            files_downloaded=success_count,
            files_failed=len(failed_files),
            failed_files=failed_files
        )

    def update_posts_basic(self, artist: Artist) -> bool:
        """Update basic post information (list) if there are new posts.

        Notes:
        - Due to backend limitations, the "list all posts" API cannot reliably return
            per-post `edited` and `content`. That means when we only call this API, we
            cannot accurately tell whether an *existing* cached post has been updated.
        - Therefore, `update_posts_basic` is intentionally designed to only determine
            whether a post exists (by id) and to refresh basic metadata; it does *not*
            attempt to detect updates.
        - Update detection is delegated to `update_posts_full`, which fetches posts
            one-by-one and can be very slow for many artists.
        - For this reason, `download_artist` uses basic updates by default, which
            implies it will not re-download posts that already exist in cache but whose
            content was updated remotely. If you need to pick up updated old posts,
            run a full cache update first (e.g. `update_all_full`).

        Returns True if cache was updated.
        """

        # Check stop flag
        if self._stop_flag.is_set():
            return False

        # Skip if artist is marked as completed or ignore
        if artist.completed or artist.ignore:
            self.logger.downloader_artist_skipped(
                artist=artist.display_name(),
                status='completed' if artist.completed else 'ignored'
            )
            return False

        profile_data = self.api.get_profile_until_success(artist.service, artist.user_id)
        newest_count = profile_data['post_count']

        cached_posts = self.cache.load_posts(artist.id, apply_filters=False)
        current_count = len(cached_posts)

        if newest_count == current_count:
            self.logger.downloader_no_new_posts(artist=artist.display_name())
            return False

        all_posts_data = self.api.get_all_posts(artist.service, artist.user_id)
        all_posts_data = reduce(
            lambda acc, x: acc if any(d['id'] == x['id'] for d in acc) else acc + [x],
            all_posts_data,
            []
        )

        if len(all_posts_data) == current_count:
            self.logger.downloader_no_new_posts(artist=artist.display_name())
            return False

        existing_posts_map = {p.id: p for p in cached_posts}
        is_new_artist = current_count == 0

        merged_posts = []
        new_count = 0

        for post_data in all_posts_data:
            post_id = str(post_data['id'])

            if post_id in existing_posts_map:
                # Keep existing post with preserved status
                merged_posts.append(existing_posts_map[post_id])
                continue

            # Create new post
            new_post = Post(
                id=post_id,
                user=post_data['user'],
                service=post_data['service'],
                title=post_data.get('title', ''),
                content=post_data.get('content', ''),
                embed=post_data.get('embed', {}),
                shared_file=post_data.get('shared_file', False),
                added=post_data.get('added', ''),
                published=post_data.get('published', ''),
                edited=post_data.get('edited'),
                file=post_data.get('file'),
                attachments=post_data.get('attachments', []),
                done=False
            )

            # Apply last_date rule only to new artists.
            #
            # Reason: when tracking an existing artist, the service may later surface
            # older posts (backfill). If we applied last_date universally, those newly
            # discovered old posts would be marked done immediately and skipped.
            #
            # If you *want* that behavior (treat anything <= last_date as done even for
            # existing artists), remove the `is_new_artist` condition.
            if is_new_artist and artist.last_date and new_post.published <= artist.last_date:
                new_post.done = True
            else:
                new_count += 1

            merged_posts.append(new_post)

        self.cache.save_posts(artist.id, merged_posts)
        self.logger.downloader_cached(artist=artist.display_name(), total=len(merged_posts), new=new_count)
        return True

    def update_posts_full(self, artist: Artist) -> int:
        """Fetch and update full post information including content for all posts.

        Returns number of posts updated.
        """
        # Check stop flag
        if self._stop_flag.is_set():
            return 0

        # Skip if artist is marked as completed or ignore
        if artist.completed or artist.ignore:
            self.logger.downloader_artist_skipped(
                artist=artist.display_name(),
                status='completed' if artist.completed else 'ignored'
            )
            return 0

        # First, update basic post list
        self.update_posts_basic(artist)

        # Load posts for full update
        posts = self.cache.load_posts(artist.id, apply_filters=False)
        if not posts:
            self.logger.downloader_no_posts(artist=artist.display_name())
            return 0

        self.logger.downloader_updating_full(artist=artist.display_name(), count=len(posts))

        updated_count = 0
        lock = threading.Lock()

        def update_post(idx_post):
            idx, post = idx_post
            try:
                # Check stop flag
                if self._stop_flag.is_set():
                    return False

                # Fetch full post
                full_post_response = self.api.get_post_until_success(artist.service, artist.user_id, post.id)
                full_post = full_post_response['post']

                changed_for_download = False

                # --- Content ---
                if 'content' in full_post:
                    remote_content = full_post.get('content', '') or ''
                    # local_content = post.content if post.content != NO_CONTENT_MARKER else ''
                    # if remote_content != local_content:
                    #     changed_for_download = True
                    post.content = remote_content if remote_content else NO_CONTENT_MARKER

                # --- File ---
                if 'file' in full_post:
                    remote_file = full_post.get('file')
                    local_file = post.file

                    # Treat local as superset: if it does NOT contain the
                    # remote file (by name/path), we consider it changed and
                    # update; otherwise we keep local richer data.
                    if not Utils.sequence_contains_all(
                        [local_file] if local_file else [],
                        [remote_file] if remote_file else [],
                        key_fields=['name', 'path']
                    ):
                        changed_for_download = True
                        post.file = remote_file

                # --- Attachments ---
                if 'attachments' in full_post:
                    remote_attachments = full_post.get('attachments', []) or []
                    local_attachments = post.attachments or []

                    if not Utils.sequence_contains_all(
                        local_attachments,
                        remote_attachments,
                        key_fields=['name', 'path']
                    ):
                        changed_for_download = True
                        post.attachments = remote_attachments

                # --- Metadata fields (do not affect done flag) ---
                if 'title' in full_post:
                    post.title = full_post['title']
                if 'embed' in full_post:
                    post.embed = full_post['embed']
                if 'shared_file' in full_post:
                    post.shared_file = full_post['shared_file']
                if 'added' in full_post:
                    post.added = full_post['added']
                if 'published' in full_post:
                    post.published = full_post['published']
                if 'edited' in full_post:
                    post.edited = full_post['edited']

                if changed_for_download:
                    post.done = False

                return changed_for_download

            except Exception as e:
                self.logger.downloader_fetch_post_failed(post_id=post.id, error=str(e), level='warning')
                return False

        with ThreadPoolExecutor(max_workers=self.config.max_concurrent_posts) as executor:
            futures = {executor.submit(update_post, (idx, post)): (idx, post)
                      for idx, post in enumerate(posts, 1)}

            for future in as_completed(futures):
                if future.result():
                    with lock:
                        updated_count += 1
                        # Log progress every 10 posts
                        if updated_count % 10 == 0:
                            self.logger.downloader_full_update_progress(updated=updated_count, total=len(posts))

        # Save updated posts
        self.cache.save_posts(artist.id, posts)

        self.logger.downloader_full_cached(artist=artist.display_name(), updated=updated_count)
        return updated_count

    # ==================== Utility Methods ====================

    def _calculate_new_last_date(self, artist: Artist) -> Optional[str]:
        """Calculate new last_date based on continuous success"""
        all_posts = self.cache.load_posts(artist.id)
        if not all_posts:
            return None

        # Sort posts by published date (oldest first)
        sorted_posts = sorted(all_posts, key=lambda p: p.published)

        # Find the starting point (current last_date or beginning)
        start_date = artist.last_date or ""

        # Find continuous success from start_date
        new_last_date = start_date
        for post in sorted_posts:
            # Skip posts before or at current last_date
            if post.published <= start_date:
                continue

            # If we hit an undone post, stop
            if not post.done:
                break

            # Update to this post's date
            new_last_date = post.published

        return new_last_date if new_last_date != start_date else None
