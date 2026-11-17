"""Compatibility shim.

The bot bridge module has moved to utils.bot_bridge.
This file remains to keep backward compatibility for existing imports.
"""

from utils.bot_bridge import (  # noqa: F401
    set_bot_instance,
    get_bot_instance,
    submit_bot_task,
)
