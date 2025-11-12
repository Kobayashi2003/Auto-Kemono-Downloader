from typing import Dict, Optional

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# ============================================================================
# Response Class
# ============================================================================

class Response:
    """Mimics requests.Response interface"""

    def __init__(self, requests_response: requests.Response):
        self._response = requests_response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> Dict[str, str]:
        return dict(self._response.headers)

    @property
    def url(self) -> str:
        return self._response.url

    @property
    def ok(self) -> bool:
        return self._response.ok

    @property
    def content(self) -> bytes:
        return self._response.content

    @property
    def text(self) -> str:
        return self._response.text

    @property
    def cookies(self):
        return self._response.cookies

    def json(self) -> Dict:
        return self._response.json()

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_content(self, chunk_size: int = 8192):
        return self._response.iter_content(chunk_size=chunk_size)


# ============================================================================
# Hybrid Session Class
# ============================================================================

class _HybridSession:
    """
    Hybrid session with two parallel paths:
    - Direct requests path (for API calls)
    - Browser path (for file downloads through proxy extension)
    """

    def __init__(self):
        self._requests_session = requests.Session()
        self._driver = None
        self._closed = False
        self.timeout = 30

    # ========== Browser Path ==========

    def _init_browser(self) -> None:
        """Initialize browser (lazy)"""
        if self._driver:
            return

        options = Options()
        options.add_argument(f'--user-data-dir=D:\\Program\\Code\\Auto-Kemono-Downloader\\temp\\chrome-profile')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--log-level=3')
        options.add_experimental_option('excludeSwitches', ['enable-logging'])

        service = Service(r"D:\Program\Code\Auto-Kemono-Downloader\temp\chromedriver.exe")
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.set_page_load_timeout(self.timeout)
        print(f"✅ Chrome WebDriver initialized")

    def _browser_get(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: Optional[int] = None,
        stream: bool = True,
        proxies: Optional[Dict] = None,
    ) -> requests.Response:
        """GET request through browser (for downloads)"""
        try:
            self._init_browser()

            # Apply headers via CDP
            if headers:
                try:
                    self._driver.execute_cdp_cmd('Network.enable', {})
                    self._driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {'headers': headers})
                except:
                    pass

            # Navigate through browser (goes through proxy extension)
            self._driver.get(url)

            # Get browser cookies
            browser_cookies = {c['name']: c['value'] for c in self._driver.get_cookies()}

            # Download with requests using browser's cookies and URL
            resp = self._requests_session.get(
                self._driver.current_url,
                headers=headers,
                cookies=browser_cookies,
                timeout=timeout or self.timeout,
                stream=stream,
                proxies=proxies
            )
            return resp

        except requests.exceptions.RequestException:
            raise
        except Exception as e:
            raise requests.exceptions.RequestException(f"Browser request failed: {e}")

    def _browser_head(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: Optional[int] = None,
        allow_redirects: bool = True,
        proxies: Optional[Dict] = None,
    ) -> requests.Response:
        """HEAD request through browser"""
        try:
            self._init_browser()

            # Apply headers
            if headers:
                try:
                    self._driver.execute_cdp_cmd('Network.enable', {})
                    self._driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {'headers': headers})
                except:
                    pass

            # Navigate through browser
            self._driver.get(url)

            # Get browser cookies
            browser_cookies = {c['name']: c['value'] for c in self._driver.get_cookies()}

            # HEAD request with browser's cookies
            resp = self._requests_session.head(
                self._driver.current_url,
                headers=headers,
                cookies=browser_cookies,
                timeout=timeout or self.timeout,
                allow_redirects=allow_redirects,
                proxies=proxies
            )
            return resp

        except requests.exceptions.RequestException:
            raise
        except Exception as e:
            raise requests.exceptions.RequestException(f"Browser HEAD request failed: {e}")

    # ========== Direct Requests Path ==========

    def _direct_get(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: Optional[int] = None,
        stream: bool = False,
        allow_redirects: bool = True,
        proxies: Optional[Dict] = None,
        **kwargs
    ) -> requests.Response:
        """GET request directly (for API calls)"""
        try:
            resp = self._requests_session.get(
                url,
                headers=headers,
                cookies=cookies,
                timeout=timeout or self.timeout,
                stream=stream,
                allow_redirects=allow_redirects,
                proxies=proxies,
                **kwargs
            )
            return resp

        except requests.exceptions.RequestException:
            raise
        except Exception as e:
            raise requests.exceptions.RequestException(f"Direct GET request failed: {e}")

    def _direct_head(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: Optional[int] = None,
        allow_redirects: bool = True,
        proxies: Optional[Dict] = None,
        **kwargs
    ) -> requests.Response:
        """HEAD request directly"""
        try:
            resp = self._requests_session.head(
                url,
                headers=headers,
                cookies=cookies,
                timeout=timeout or self.timeout,
                allow_redirects=allow_redirects,
                proxies=proxies,
                **kwargs
            )
            return resp

        except requests.exceptions.RequestException:
            raise
        except Exception as e:
            raise requests.exceptions.RequestException(f"Direct HEAD request failed: {e}")

    # ========== Public Interface ==========

    @property
    def cookies(self):
        """Return requests session cookies"""
        return self._requests_session.cookies

    def _is_api_call(self, url: str) -> bool:
        """Check if URL is an API call"""
        return '/api/v1/' in url

    def get(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: Optional[int] = None,
        stream: bool = False,
        allow_redirects: bool = True,
        proxies: Optional[Dict] = None,
        **kwargs
    ) -> Response:
        """
        Smart GET:
        - API calls -> direct requests
        - File downloads -> browser path
        """
        if self._closed:
            raise RuntimeError("Session is closed")

        if self._is_api_call(url):
            resp = self._direct_get(url, headers, cookies, timeout, stream, allow_redirects, proxies, **kwargs)
        else:
            resp = self._browser_get(url, headers, cookies, timeout, stream, proxies)

        return Response(resp)

    def head(
        self,
        url: str,
        headers: Optional[Dict] = None,
        cookies: Optional[Dict] = None,
        timeout: Optional[int] = None,
        allow_redirects: bool = True,
        proxies: Optional[Dict] = None,
        **kwargs
    ) -> Response:
        """
        Smart HEAD:
        - API calls -> direct requests
        - File downloads -> browser path
        """
        if self._closed:
            raise RuntimeError("Session is closed")

        if self._is_api_call(url):
            resp = self._direct_head(url, headers, cookies, timeout, allow_redirects, proxies, **kwargs)
        else:
            resp = self._browser_head(url, headers, cookies, timeout, allow_redirects, proxies)

        return Response(resp)

    # ========== Lifecycle ==========

    def close(self) -> None:
        """Close both sessions"""
        if self._closed:
            return

        self._closed = True

        try:
            self._requests_session.close()
        except:
            pass

        if self._driver:
            try:
                self._driver.quit()
            except:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        if not self._closed:
            try:
                self.close()
            except:
                pass


# ============================================================================
# Factory Function
# ============================================================================

def Session():
    """
    Create hybrid session with two parallel paths:
    - Direct requests for API calls (fast)
    - Browser for downloads (through proxy extension)
    """
    return _HybridSession()


# ============================================================================
# Exception Classes
# ============================================================================

class exceptions:
    """Requests exception classes"""
    RequestException = requests.exceptions.RequestException
    Timeout = requests.exceptions.Timeout
    ConnectionError = requests.exceptions.ConnectionError
    HTTPError = requests.exceptions.HTTPError