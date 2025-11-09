"""JSON editor using prompt_toolkit with vim mode"""

import json
from typing import Optional

from prompt_toolkit import Application
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame, TextArea


def edit_json(data: dict, title: str = "Edit Config") -> Optional[dict]:
    """Edit JSON in full-screen vim editor

    Keybindings:
        Ctrl+S  - Save and exit
        Ctrl+Q  - Exit without saving

    Vim mode is enabled (hjkl, i/a/o, v, dd, yy, p, etc.)

    Args:
        data: Dictionary to edit
        title: Window title
    """

    json_text = json.dumps(data, indent=2, ensure_ascii=False)

    text_area = TextArea(
        text=json_text,
        multiline=True,
        scrollbar=True,
        line_numbers=True,
        wrap_lines=False,
    )

    status_text = "[VIM] Ctrl+S: Save & Exit | Ctrl+Q: Cancel"
    status_bar = Window(
        content=FormattedTextControl(text=status_text),
        height=1,
        style='reverse',
    )

    error_message = {"text": ""}
    error_bar = Window(
        content=FormattedTextControl(lambda: error_message["text"]),
        height=1,
        style='bg:#ff0000 #ffffff' if error_message["text"] else '',
    )

    result = {"data": None, "saved": False}
    kb = KeyBindings()

    @kb.add('c-s')
    def save_and_exit(event):
        try:
            result["data"] = json.loads(text_area.text)
            result["saved"] = True
            event.app.exit()
        except json.JSONDecodeError as e:
            error_message["text"] = f"JSON Error: {e}"
            event.app.invalidate()

    @kb.add('c-q')
    def cancel(event):
        event.app.exit()

    layout = Layout(
        HSplit([
            Frame(text_area, title=title),
            error_bar,
            status_bar,
        ])
    )

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        editing_mode=EditingMode.VI,
    )

    app.run()

    return result["data"] if result["saved"] else None
