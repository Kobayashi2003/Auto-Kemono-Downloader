"""Minimal dynamic plugin loader.

Reloads `user_plugins.py` on every call so edits take effect immediately.
Example:
    from src.plugins import dynamic_call
    result = dynamic_call('process', 10)
"""

from __future__ import annotations

import importlib.util
import pathlib
import types
from typing import Any


def _load_module(module_filename: str) -> types.ModuleType:
    base_dir = pathlib.Path(__file__).resolve().parent.parent  # project root
    path = base_dir / module_filename
    if not path.exists():
        raise FileNotFoundError(f"Plugin file not found: {path}")
    spec = importlib.util.spec_from_file_location(module_filename[:-3], path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create spec for {module_filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


def dynamic_call(func_name: str, module_filename: str, *args: Any, default=None, **kwargs: Any) -> Any:
    """If args are provided: reload module and invoke function.

    If no args: reload module and return the function object (e.g. for decorator usage).
    """
    if not module_filename:
        raise ValueError("module_filename must be provided")
    module = _load_module(module_filename)
    func = getattr(module, func_name, None) or default
    if not callable(func):
        raise AttributeError(f"Function '{func_name}' not found or not callable in {module_filename}")
    if not args and not kwargs:
        return func  # Return function for @decorator use
    return func(*args, **kwargs)


class PluginExecutor:
    """Callable wrapper that reloads plugin file every invocation.

    Example:
        executor = PluginExecutor(func_name='process')
        result = executor(data)
    """

    def __init__(self, func_name: str, module_filename: str = "user_plugins.py"):
        self.func_name = func_name
        self.module_filename = module_filename

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return dynamic_call(self.func_name, *args, module_filename=self.module_filename, **kwargs)


__all__ = ["dynamic_call", "PluginExecutor"]
