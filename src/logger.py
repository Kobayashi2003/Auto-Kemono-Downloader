import logging
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler


class Logger:
    def __init__(self, log_dir: str, console_output: bool = False):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        self.logger = logging.getLogger("kemono")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        log_filename = datetime.now().strftime("%Y-%m-%d.log")
        file_handler = RotatingFileHandler(
            self.log_dir / log_filename,
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        if console_output:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

    # ==================== Basic Logging Methods ====================

    def info(self, msg: str):
        self.logger.info(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def debug(self, msg: str):
        self.logger.debug(msg)

    # ==================== Artist Level Messages ====================

    # Status messages
    def artist_resumed(self, artist_name: str):
        """Artist was resumed from paused state"""
        self.info(f"Resumed: {artist_name}")

    def artist_no_new_posts(self, artist_name: str):
        """No new posts detected for artist"""
        self.info(f"{artist_name}: No new posts")

    def artist_no_posts(self, artist_name: str, reason: str = "No posts found"):
        """No posts to process"""
        self.info(f"{artist_name}: {reason}")

    def artist_failed(self, artist_name: str, error: str):
        """Artist processing failed"""
        self.error(f"{artist_name} failed: {error}")

    def artist_skipped(self, artist_name: str):
        """Artist skipped (marked as completed)"""
        self.info(f"{artist_name}: Skipped (marked as completed)")

    # Basic cache operations
    def artist_updating_cache(self, artist_name: str):
        """Updating basic cache for artist"""
        self.info(f"{artist_name}: Updating cache (new posts detected)")

    def artist_cached(self, artist_name: str, total: int, new: int):
        """Basic cache updated for artist"""
        self.info(f"{artist_name}: Cached {total} posts, {new} new")

    # Full cache operations
    def artist_updating_full(self, artist_name: str, count: int):
        """Updating full post information"""
        self.info(f"{artist_name}: Updating full info for {count} posts")

    def artist_full_cached(self, artist_name: str, updated: int):
        """Full post information cached"""
        self.info(f"{artist_name}: Cached full info for {updated} posts")

    # Download operations
    def artist_processing_posts(self, artist_name: str, count: int):
        """Starting to process posts"""
        self.info(f"{artist_name}: Processing {count} posts")

    def artist_completed(self, artist_name: str, succeeded: int, failed: int):
        """Artist processing completed"""
        self.info(f"{artist_name}: Completed - {succeeded} succeeded, {failed} failed")

    def artist_downloaded(self, artist_name: str, posts_count: int):
        """Artist download summary"""
        self.info(f"{artist_name}: {posts_count} posts downloaded")

    def artist_updated_last_date(self, artist_name: str, last_date: str):
        """Updated last_date for artist"""
        self.info(f"{artist_name}: Updated last_date to {last_date}")

    # ==================== Post Level Messages ====================

    def post_processing(self, index: int, total: int, title: str, file_count: int):
        """Processing a post"""
        self.info(f"[{index}/{total}] {title[:40]} ({file_count} files)")

    def post_success(self, downloaded: int, total: int):
        """Post downloaded successfully"""
        self.info(f"  ✓ Downloaded {downloaded}/{total} files")

    def post_failed(self, failed: int, total: int):
        """Post download failed"""
        self.info(f"  ✗ Failed {failed}/{total} files")

    def post_error(self, post_id: str, error: str):
        """Post processing error"""
        self.error(f"Post {post_id} failed with error: {error}")

    # ==================== File Level Messages ====================

    def file_success(self, filename: str):
        """File downloaded successfully"""
        self.info(f"    ✓ {filename}")

    def file_failed(self, filename: str, error: str):
        """File download failed"""
        self.error(f"    ✗ {filename} - {error}")

    # ==================== Network & Retry Messages ====================

    def network_error(self, operation: str, error: str, retry_delay: int):
        """Network error occurred, will retry"""
        self.warning(f"Network error during {operation}: {error}, retrying in {retry_delay}s...")

    def session_initialized(self, cookie_count: int):
        """API session initialized"""
        self.info(f"Session initialized: {cookie_count} cookies")

    def session_init_failed(self, error: str):
        """API session initialization failed"""
        self.warning(f"Session init failed: {error}")
