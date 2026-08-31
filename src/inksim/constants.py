
"""Application constants shared by the InkSim modules."""

import getpass
import os


def _make_ipc_server_name():
    """Return a per-user IPC endpoint name.

    Multiple users on the same machine must each have their own server, so the
    name includes the current user's id.  ``os.getuid`` is used on Unix-like
    platforms; on Windows ``getpass.getuser`` is the fallback.
    """
    try:
        user_id = os.getuid()
    except AttributeError:
        user_id = getpass.getuser()
    return f"inksim-local-{user_id}"


APP_TITLE = "InkSim"
APP_ORGANIZATION = "InkSim"
IPC_SERVER_NAME = _make_ipc_server_name()
IPC_PROTOCOL_VERSION = 1
TOKEN_FILENAME = "inksim-server.token"
DEFAULT_STATUS_TEXT = (
	"Space=play/pause | C=center | F=fit | F11=fullscreen | "
	"Ctrl+Arrows=color | G=grid H=help"
)
DENSITY_RADIUS_MM = 2.5
DENSITY_WARNING_PER_MM2 = 3.0
DENSITY_CRITICAL_PER_MM2 = 6.0
DEFAULT_LINE_WIDTH_MM = 0.4
DEFAULT_DARK_FACTOR = 0.50
DEFAULT_LIGHT_FACTOR = 0.50
DEFAULT_BACKGROUND_COLOR = (0, 0, 0)
DEFAULT_NEEDLE_COLOR = (255, 255, 255)
DEFAULT_NEEDLE_RADIUS = 30.0
DEFAULT_NEEDLE_WIDTH = 1.0
NEEDLE_RADIUS_MIN = 10.0
NEEDLE_RADIUS_MAX = 100.0
NEEDLE_WIDTH_MIN = 0.5
NEEDLE_WIDTH_MAX = 5.0
MAX_RENDER_LINE_WIDTH_PX = 16.0
MAX_RENDER_STEPS = 2048
MIN_VISIBLE_DESIGN_PIXELS = 100.0
MAX_ZOOM_DESIGN_MM = 5.0
REALISTIC_END_FADE_PX = 4.0
AUTO_THREAD_COLORS = (
	(220, 30, 30),
	(30, 100, 220),
	(30, 160, 80),
	(230, 150, 25),
	(150, 60, 180),
	(20, 170, 180),
	(220, 70, 140),
	(110, 110, 110),
)
