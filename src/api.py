import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .proxy_pool import ProxyPool


class API:
    BASE_URL = "https://kemono.cr"

    INIT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'DNT': '1',
        'Sec-GPC': '1',
        'Upgrade-Insecure-Requests': '1',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Priority': 'u=0, i',
    }

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0',
        'Accept': 'text/css',
        'Accept-Language': 'en-US,en;q=0.5',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
    }

    def __init__(self, logger, proxy_pool: Optional[ProxyPool] = None):
        self.logger = logger
        self.session = requests.Session()
        self.cookies = {}
        self.proxy_pool = proxy_pool
        self._stop_flag = threading.Event()  # Cancel flag for graceful shutdown
        self._init()

    # ==================== Initialization ====================

    def _init(self):
        try:
            resp = self.session.get(self.BASE_URL, headers=self.INIT_HEADERS, timeout=10)
            self.cookies = resp.cookies.get_dict()
            self.logger.api_session_initialized(cookies=len(self.cookies))
        except Exception as e:
            self.logger.api_session_init_failed(error=str(e), level='warning')

    def stop(self):
        """Stop all ongoing requests and close session"""
        self._stop_flag.set()
        try:
            self.session.close()
        except:
            pass
        self.logger.api_session_stopped()

    def resume(self):
        """Resume after cancel - reinitialize session"""
        self._stop_flag.clear()
        self.session = requests.Session()
        self._init()
        self.logger.api_session_resumed()

    # ==================== Utility Methods ====================

    def _retry_until_success(self, func, error_msg: str, retry_delay: int = 5):
        """Retry a function until it succeeds (only for network errors)"""
        while True:
            # Check cancel flag before each attempt
            if self._stop_flag.is_set():
                raise InterruptedError("Request cancelled")

            try:
                return func()
            except (
                requests.exceptions.RequestException,  # All requests exceptions
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,
                ConnectionError,
                TimeoutError,
            ) as e:
                # Check if cancelled (session.close() causes ConnectionError)
                if self._stop_flag.is_set():
                    raise InterruptedError("Request cancelled")

                # Network errors - retry with delay
                self.logger.api_network_error(operation=error_msg, error=str(e), retry_delay=retry_delay, level='warning')
                time.sleep(retry_delay)
            except Exception as e:
                # Other errors - don't retry, raise immediately
                raise

    # ==================== Basic API Methods ====================

    def get_profile(self, service: str, user_id: str) -> Optional[Dict]:
        if self._stop_flag.is_set():
            raise InterruptedError("Request cancelled")
        url = f"{self.BASE_URL}/api/v1/{service}/user/{user_id}/profile"
        proxies = self.proxy_pool.get_proxy() if self.proxy_pool else None
        resp = self.session.get(url, cookies=self.cookies, headers=self.HEADERS, proxies=proxies, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_posts(self, service: str, user_id: str, offset: int = 0) -> List[Dict]:
        if self._stop_flag.is_set():
            raise InterruptedError("Request cancelled")
        url = f"{self.BASE_URL}/api/v1/{service}/user/{user_id}/posts"
        if offset > 0:
            url += f"?o={offset}"
        proxies = self.proxy_pool.get_proxy() if self.proxy_pool else None
        resp = self.session.get(url, cookies=self.cookies, headers=self.HEADERS, proxies=proxies, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_post(self, service: str, user_id: str, post_id: str) -> Optional[Dict]:
        if self._stop_flag.is_set():
            raise InterruptedError("Request cancelled")
        url = f"{self.BASE_URL}/api/v1/{service}/user/{user_id}/post/{post_id}"
        proxies = self.proxy_pool.get_proxy() if self.proxy_pool else None
        resp = self.session.get(url, cookies=self.cookies, headers=self.HEADERS, proxies=proxies, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_content_length(self, url: str) -> Optional[int]:
        """Get content-length from URL (HEAD request with redirects)"""
        if self._stop_flag.is_set():
            raise InterruptedError("Request cancelled")

        proxies = self.proxy_pool.get_proxy() if self.proxy_pool else None

        resp = self.session.head(url, cookies=self.cookies, headers=self.HEADERS, proxies=proxies, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        content_length = resp.headers.get('content-length')
        return int(content_length) if content_length else None

    def download_file(self, url: str, save_path: str, raise_on_error: bool = False,
                     on_start=None, on_progress=None, on_complete=None) -> bool:
        """
        Download file with optional progress callbacks

        Callbacks:
            on_start(filename, content_length) - Called when download starts
            on_progress(filename, downloaded, content_length) - Called during download
            on_complete(filename, success) - Called when download completes/fails
        """
        temp_path = None
        try:
            # Check cancel flag at start
            if self._stop_flag.is_set():
                raise InterruptedError("Download cancelled")

            path = Path(save_path)
            filename = path.name

            # Download to temp file first
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + '.tmp')

            # Delete existing temp file if any (from previous failed download)
            while temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    time.sleep(0.1)

            # Start actual download
            proxies = self.proxy_pool.get_proxy() if self.proxy_pool else None
            resp = self.session.get(url, cookies=self.cookies, headers=self.HEADERS, proxies=proxies, timeout=60, stream=True)
            resp.raise_for_status()

            # Get content-length
            content_length = int(resp.headers.get('content-length', 0)) or self.get_content_length_until_success(url) or 0

            # Check if file exists and validate size
            if content_length and path.exists():
                actual_size = path.stat().st_size
                if actual_size == content_length:
                    # File exists and size matches, skip download
                    if on_complete:
                        on_complete(filename, True)
                    return True
                # If size mismatch, continue to download (will add suffix to avoid overwrite)

            # Callback: download started
            if on_start:
                on_start(filename, content_length)

            downloaded = 0
            with open(temp_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    # Check cancel flag in download loop
                    if self._stop_flag.is_set():
                        resp.close()
                        f.close()
                        # Clean up temp file
                        if temp_path.exists():
                            temp_path.unlink()
                        raise InterruptedError("Download cancelled")

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Callback: progress update
                        if on_progress:
                            on_progress(filename, downloaded, content_length)

            # Rename temp file to final name
            # If file exists (size mismatch or no content-length), add suffix
            final_path = path
            if final_path.exists():
                counter = 1
                stem = final_path.stem
                suffix = final_path.suffix
                parent = final_path.parent

                while final_path.exists():
                    final_path = parent / f"{stem} ({counter}){suffix}"
                    counter += 1

            temp_path.rename(final_path)

            # Callback: download completed
            if on_complete:
                on_complete(filename, True)

            return True

        except InterruptedError:
            # Clean up temp file on cancellation
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass

            # Callback: download cancelled
            if on_complete:
                try:
                    on_complete(Path(save_path).name, False)
                except:
                    pass

            if raise_on_error:
                raise
            return False

        except Exception as e:
            # Clean up temp file if exists
            try:
                temp_path = Path(save_path).with_suffix(Path(save_path).suffix + '.tmp')
                if temp_path.exists():
                    temp_path.unlink()
            except:
                pass

            # Callback: download failed
            if on_complete:
                try:
                    on_complete(Path(save_path).name, False)
                except:
                    pass

            if raise_on_error:
                raise
            return False

    # ==================== Retry-Enabled API Methods ====================

    def get_content_length_until_success(self, url: str) -> Optional[int]:
        """Get content-length with retry until success"""
        return self._retry_until_success(
            lambda: self.get_content_length(url),
            f"Failed to get content-length for {url}"
        )

    def get_profile_until_success(self, service: str, user_id: str) -> Dict:
        """Get profile with retry until success"""
        return self._retry_until_success(
            lambda: self.get_profile(service, user_id),
            f"Failed to get profile for {service}/{user_id}"
        )

    def get_post_until_success(self, service: str, user_id: str, post_id: str) -> Dict:
        """Get a single post with retry until success"""
        return self._retry_until_success(
            lambda: self.get_post(service, user_id, post_id),
            f"Failed to get post {post_id}"
        )

    def get_posts_until_success(self, service: str, user_id: str, offset: int = 0) -> List[Dict]:
        """Get posts with retry until success"""
        return self._retry_until_success(
            lambda: self.get_posts(service, user_id, offset),
            f"Failed to get posts at offset {offset}"
        )

    def get_all_posts(self, service: str, user_id: str) -> List[Dict]:
        """Fetch all posts for an artist with retry logic (concurrent page fetching)"""
        # Get profile to know total post count
        profile = self.get_profile_until_success(service, user_id)
        post_count = profile['post_count']

        # Calculate total pages needed
        posts_per_page = 50
        total_pages = (post_count + posts_per_page - 1) // posts_per_page

        if total_pages == 0:
            return []

        if total_pages == 1:
            # Single page, no need for concurrency
            return self.get_posts_until_success(service, user_id, 0)

        # Fetch pages concurrently
        all_posts = []

        def fetch_page(page):
            offset = page * posts_per_page
            return (page, self.get_posts_until_success(service, user_id, offset))

        with ThreadPoolExecutor(max_workers=min(5, total_pages)) as executor:
            futures = {executor.submit(fetch_page, page): page
                      for page in range(total_pages)}

            # Collect results in order
            results = {}
            for future in as_completed(futures):
                page, batch = future.result()
                results[page] = batch

            # Combine in correct order
            for page in range(total_pages):
                all_posts.extend(results[page])

        return all_posts

    def download_file_until_success(self, url: str, save_path: str,
                                   on_start=None, on_progress=None, on_complete=None) -> bool:
        """Download file with retry until success and optional progress callbacks"""
        return self._retry_until_success(
            lambda: self.download_file(url, save_path, raise_on_error=True,
                                      on_start=on_start, on_progress=on_progress, on_complete=on_complete),
            f"Failed to download file {save_path}"
        )
