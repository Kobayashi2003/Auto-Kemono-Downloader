"""Prompt helper for CLI interaction"""

from typing import List

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import History
from prompt_toolkit.shortcuts import PromptSession as PromptSessionBase

from .storage import Storage


class JSONHistory(History):
    """Load command history from storage"""

    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage

    async def load(self):
        """Load history items"""
        try:
            records = self.storage.get_history(limit=1000)
            for record in records:
                yield record.command
        except:
            pass

    def load_history_strings(self) -> List[str]:
        """Load command strings for sync access"""
        try:
            records = self.storage.get_history(limit=1000)
            return [record.command for record in reversed(records)]
        except:
            return []

    def store_string(self, string: str) -> None:
        """Store string (compatibility method)"""
        pass


class CommandCompleter(Completer):
    """Command completer with dynamic command loading"""

    def __init__(self, get_commands_func):
        """Initialize with function that returns command map"""
        self.get_commands_func = get_commands_func

    def get_completions(self, document: Document, complete_event):
        """Get completions with dynamically loaded commands"""
        commands = sorted(self.get_commands_func().keys())
        text = document.text_before_cursor.lower()

        if ':' in text:
            return

        if not text:
            for cmd in commands:
                yield Completion(cmd, start_position=0, display=cmd)
        else:
            for cmd in commands:
                if text in cmd:
                    yield Completion(cmd, start_position=-len(text), display=cmd)


class CLIPromptSession:
    """CLI prompt session with history and dynamic command completion"""

    def __init__(self, storage: Storage, get_commands_func):
        """Initialize with storage and command getter function"""
        self.storage = storage
        self.history = JSONHistory(storage)
        self.completer = CommandCompleter(get_commands_func)

        self._session = PromptSessionBase(
            history=self.history,
            completer=self.completer
        )

    def prompt(self, message: str = "> ") -> str:
        """Get user input with history and completion support"""
        return self._session.prompt(message).strip().lower()
