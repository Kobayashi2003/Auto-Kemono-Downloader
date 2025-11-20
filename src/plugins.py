"""Minimal dynamic plugin loader.

Reloads plugin file on every call so edits take effect immediately.

Functions:
    dynamic_call: Call a function from plugin file
    dynamic_get: Get a variable from plugin file

Classes:
    PluginExecutor: Callable wrapper for functions
    VariableLoader: Helper for loading multiple variables

Examples:
    from src.plugins import dynamic_call, dynamic_get, VariableLoader

    # Call a function
    result = dynamic_call('process', 'user_plugins.py', 10)

    # Get a variable
    config = dynamic_get('CONFIG', 'user_plugins.py', default={})

    # Load multiple variables
    loader = VariableLoader('user_plugins.py')
    api_key = loader.get('API_KEY')
    config = loader.get_multiple('HOST', 'PORT')
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
    """Call function from plugin file (reload on each call)"""
    if not module_filename:
        raise ValueError("module_filename must be provided")
    module = _load_module(module_filename)
    func = getattr(module, func_name, None) or default
    if not callable(func):
        raise AttributeError(f"Function '{func_name}' not found or not callable in {module_filename}")
    if not args and not kwargs:
        return func  # Return function for @decorator use
    return func(*args, **kwargs)


def dynamic_get(var_name: str, module_filename: str, default=None) -> Any:
    """Get variable from plugin file (reload on each call)"""
    if not module_filename:
        raise ValueError("module_filename must be provided")
    module = _load_module(module_filename)
    value = getattr(module, var_name, None)
    if value is None:
        if default is None:
            raise AttributeError(f"Variable '{var_name}' not found in {module_filename}")
        return default
    return value


class PluginExecutor:
    """Callable wrapper for function invocation with dynamic reload"""

    def __init__(self, func_name: str, module_filename: str = "user_plugins.py"):
        self.func_name = func_name
        self.module_filename = module_filename

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return dynamic_call(self.func_name, *args, module_filename=self.module_filename, **kwargs)


class VariableLoader:
    """Helper for loading variables from plugin files"""

    def __init__(self, module_filename: str = "user_plugins.py"):
        self.module_filename = module_filename

    def get(self, var_name: str, default=None) -> Any:
        """Get single variable from plugin file"""
        return dynamic_get(var_name, self.module_filename, default)

    def get_multiple(self, *var_names: str) -> dict:
        """Get multiple variables (all must exist)"""
        result = {}
        for var_name in var_names:
            result[var_name] = dynamic_get(var_name, self.module_filename)
        return result

    def get_all(self, *var_names: str, allow_missing: bool = False) -> dict:
        """Get multiple variables (optionally allow missing ones)"""
        result = {}
        for var_name in var_names:
            try:
                result[var_name] = dynamic_get(var_name, self.module_filename)
            except AttributeError:
                if allow_missing:
                    result[var_name] = None
                else:
                    raise
        return result


__all__ = ["dynamic_call", "dynamic_get", "PluginExecutor", "VariableLoader"]
