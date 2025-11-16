import logging
import functools
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

    # ==================== Standardized Event Logging ====================

    def _normalize(self, value) -> str:
        """Normalize message parts to a compact single-line string."""
        try:
            text = str(value)
        except Exception:
            text = repr(value)
        # Replace newlines and compress spaces
        text = text.replace('\n', ' ').replace('\r', ' ')
        while '  ' in text:
            text = text.replace('  ', ' ')
        return text.strip()

    def _emit(self, level: str, module: str, action: str, message: str = ""):
        """Emit a standardized log line with module and action.

        Format: "[MODULE] action - message"
        """
        module_tag = module.strip().upper() if module else "APP"
        action_name = action.strip() if action else "event"
        msg = f"[{module_tag}] {action_name}"
        if message:
            msg = f"{msg} - {self._normalize(message)}"

        lvl = level.lower()
        if lvl == 'error':
            self.logger.error(msg)
        elif lvl == 'warning' or lvl == 'warn':
            self.logger.warning(msg)
        elif lvl == 'debug':
            self.logger.debug(msg)
        else:
            self.logger.info(msg)

    def event(self, level: str = 'info', name: str | None = None):
        """Decorator to log function calls with module name automatically.

        Usage:
            @logger.event(level='info')
            def some_function(...):
                ...

        The module is derived from func.__module__ (last segment). The action
        defaults to the function's name, or can be overridden via 'name'.
        """
        def decorator(func):
            module = (func.__module__ or '').split('.')[-1] or 'app'
            action = name or func.__name__

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # Log function entry
                self._emit(level, module, action, "call")
                return func(*args, **kwargs)

            return wrapper

        return decorator

    def __getattr__(self, attr: str):
        """Dynamic event functions by naming convention: module_action(...)

        Enforces the prefix 'module_' to keep naming consistent. Example:
            logger.downloader_artist_skipped(artist_name="Alice")

        You can pass a positional message string or keyword details. Optional
        keyword 'level' overrides the level (info|warning|error|debug).
        """
        if '_' not in attr:
            # Enforce the naming rule to keep logs consistent
            raise AttributeError(
                f"Logger event '{attr}' must be named as 'module_action'."
            )

        module, action = attr.split('_', 1)

        def _event(*args, **kwargs):
            level = kwargs.pop('level', 'info')
            # Build message from positional text or structured kwargs
            message = None
            if args:
                message = ' '.join(self._normalize(a) for a in args)
            if kwargs:
                # Append structured fields if provided
                fields = ', '.join(f"{k}={self._normalize(v)}" for k, v in kwargs.items())
                message = f"{message + ' | ' if message else ''}{fields}" if fields else (message or '')

            self._emit(level, module, action, message or '')

        return _event

    # ==================== Basic Logging Methods ====================

    def info(self, msg: str):
        self.logger.info(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def debug(self, msg: str):
        self.logger.debug(msg)