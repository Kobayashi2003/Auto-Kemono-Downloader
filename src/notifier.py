class Notifier:
    """Base notifier class"""

    def __init__(self, enabled: bool = True):
        """
        Initialize notifier

        Args:
            enabled: Whether to enable notifications (default: True)
        """
        self._impl = ConsoleNotifier() if enabled else NullNotifier()

    def on_download_start(self, filename: str, total_size: int):
        """Called when a file download starts"""
        self._impl.on_download_start(filename, total_size)

    def on_download_progress(self, filename: str, downloaded: int, total_size: int):
        """Called during file download"""
        self._impl.on_download_progress(filename, downloaded, total_size)

    def on_download_complete(self, filename: str, success: bool):
        """Called when a file download completes or fails"""
        self._impl.on_download_complete(filename, success)

    def notify_artist_start(self, artist_name: str, post_count: int):
        """Notify when starting to process an artist"""
        self._impl.notify_artist_start(artist_name, post_count)

    def notify_artist_complete(self, artist_name: str, succeeded: int, failed: int):
        """Notify when artist processing completes"""
        self._impl.notify_artist_complete(artist_name, succeeded, failed)


class NullNotifier:
    """No-op notifier that does nothing"""

    def on_download_start(self, filename: str, total_size: int):
        pass

    def on_download_progress(self, filename: str, downloaded: int, total_size: int):
        pass

    def on_download_complete(self, filename: str, success: bool):
        pass

    def notify_artist_start(self, artist_name: str, post_count: int):
        pass

    def notify_artist_complete(self, artist_name: str, succeeded: int, failed: int):
        pass


class ConsoleNotifier:
    """Console-based progress notifier"""

    def __init__(self):
        self._last_percent = -1

    def on_download_start(self, filename: str, total_size: int):
        """Called when a file download starts"""
        if total_size > 0:
            size_mb = total_size / (1024 * 1024)
            print(f"    Downloading: {filename} ({size_mb:.2f} MB)")
        else:
            print(f"    Downloading: {filename}")
        self._last_percent = -1

    def on_download_progress(self, filename: str, downloaded: int, total_size: int):
        """Called during file download"""
        if total_size > 0:
            percent = int(downloaded / total_size * 100)
            # Update every 25%
            if percent >= self._last_percent + 25:
                print(f"    Progress: {filename} - {percent}%")
                self._last_percent = percent

    def on_download_complete(self, filename: str, success: bool):
        """Called when a file download completes or fails"""
        pass  # Already logged by logger

    def notify_artist_start(self, artist_name: str, post_count: int):
        """Notify when starting to process an artist"""
        pass  # Already logged by logger

    def notify_artist_complete(self, artist_name: str, succeeded: int, failed: int):
        """Notify when artist processing completes"""
        pass  # Already logged by logger
