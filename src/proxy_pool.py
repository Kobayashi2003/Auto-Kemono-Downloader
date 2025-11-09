"""
Proxy pool for multi-IP concurrent requests with auto Clash management
"""
import atexit
import os
import subprocess
import threading
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional


class ProxyPool:
    """Thread-safe proxy pool with round-robin rotation"""

    def __init__(self, proxies: Optional[List[Dict[str, str]]] = None):
        self.proxies = proxies or []
        self.current_index = 0
        self.lock = threading.Lock()

    def get_proxy(self) -> Optional[Dict[str, str]]:
        if not self.proxies:
            return None
        with self.lock:
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)
            return proxy

    def size(self) -> int:
        return len(self.proxies)


class NullProxyPool(ProxyPool):
    """Null proxy pool (no proxy)"""

    def __init__(self):
        super().__init__([])

    def get_proxy(self) -> None:
        return None

    def cleanup(self):
        """No-op cleanup for null proxy pool"""
        pass


class ClashProxyPool(ProxyPool):
    """Clash proxy pool with auto management (Singleton)"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, clash_exe: str, clash_config: str, base_port: int = 7890,
                 num_instances: int = 10, temp_dir: str = "temp",
                 proxy_filter=None, skip_keywords=None, logger=None):
        """
        Args:
            clash_exe: Path to clash executable
            clash_config: Path to clash config
            base_port: Starting port
            num_instances: Number of instances
            temp_dir: Temp directory
            proxy_filter: Custom filter function(proxy_dict) -> bool
            skip_keywords: List of keywords to skip in proxy names
            logger: Logger instance
        """
        if hasattr(self, '_initialized'):
            return

        # Validate required parameters
        if not clash_exe:
            raise ValueError("clash_exe is required")
        if not clash_config:
            raise ValueError("clash_config is required")
        if not Path(clash_exe).exists():
            raise FileNotFoundError(f"Clash executable not found: {clash_exe}")
        if not Path(clash_config).exists():
            raise FileNotFoundError(f"Clash config not found: {clash_config}")
        if base_port < 1024 or base_port > 65535:
            raise ValueError(f"Invalid base_port: {base_port} (must be 1024-65535)")
        if num_instances < 1 or num_instances > 50:
            raise ValueError(f"Invalid num_instances: {num_instances} (must be 1-50)")

        self.clash_exe = clash_exe
        self.clash_config = clash_config
        self.base_port = base_port
        self.num_instances = num_instances
        self.logger = logger
        self.processes = []
        self.temp_dir = Path(temp_dir) / "clash_instances"

        # Configurable filter
        self.proxy_filter = proxy_filter
        self.skip_keywords = skip_keywords or ['DIRECT', 'REJECT']

        self._setup()
        atexit.register(self.cleanup)
        self._initialized = True

    def _log(self, message: str):
        if self.logger:
            self.logger.info(message)
        else:
            print(f"[ProxyPool] {message}")

    def _setup(self):
        self._log(f"Setting up {self.num_instances} Clash instances...")

        try:
            with open(self.clash_config, 'r', encoding='utf-8') as f:
                base_config = yaml.safe_load(f)
        except Exception as e:
            self._log(f"Failed to load config: {e}")
            super().__init__([])
            return

        available_proxies = self._get_available_proxies(base_config)
        if len(available_proxies) < self.num_instances:
            self.num_instances = min(self.num_instances, len(available_proxies))

        self.temp_dir.mkdir(parents=True, exist_ok=True)

        proxies = []
        for i in range(self.num_instances):
            port = self.base_port + (i * 10)
            controller_port = 9090 + i
            proxy_node = available_proxies[i]

            config_file = self._create_config(base_config, proxy_node, port, controller_port, i)
            if config_file and self._start_instance(config_file, i):
                proxies.append({
                    'http': f'http://127.0.0.1:{port}',
                    'https': f'http://127.0.0.1:{port}'
                })

        super().__init__(proxies)

        if proxies:
            time.sleep(3)
            self._log(f"Started {len(proxies)} Clash instances")

    def _get_available_proxies(self, config: dict) -> List[dict]:
        """Get available proxies with configurable filter"""
        proxies = config.get('proxies', [])
        available = []

        for proxy in proxies:
            # Use custom filter if provided
            if self.proxy_filter:
                if self.proxy_filter(proxy):
                    available.append(proxy)
            else:
                # Default filter: skip by keywords
                name = proxy.get('name', '')
                if not any(skip in name for skip in self.skip_keywords):
                    available.append(proxy)

        return available

    def _create_config(self, base_config: dict, proxy_node: dict, port: int,
                      controller_port: int, index: int) -> Optional[Path]:
        try:
            new_config = base_config.copy()
            new_config['port'] = port
            new_config['socks-port'] = port + 1
            new_config['external-controller'] = f'0.0.0.0:{controller_port}'
            new_config['secret'] = ''
            new_config['proxies'] = [proxy_node]

            proxy_name = proxy_node['name']
            new_config['proxy-groups'] = [
                {'name': 'PROXY', 'type': 'select', 'proxies': [proxy_name]}
            ]
            new_config['rules'] = ['MATCH,PROXY']

            config_file = self.temp_dir / f"clash_{index}.yaml"
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(new_config, f, allow_unicode=True, default_flow_style=False)

            return config_file
        except Exception as e:
            self._log(f"Failed to create config {index}: {e}")
            return None

    def _start_instance(self, config_file: Path, index: int) -> bool:
        try:
            process = subprocess.Popen(
                [self.clash_exe, '-f', str(config_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self.processes.append(process)
            return True
        except Exception as e:
            self._log(f"Failed to start instance {index}: {e}")
            return False

    def cleanup(self):
        if not self.processes:
            return
        self._log(f"Stopping {len(self.processes)} Clash instances...")
        for process in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass
        self.processes.clear()
        self._log("All instances stopped")

    def __del__(self):
        self.cleanup()
