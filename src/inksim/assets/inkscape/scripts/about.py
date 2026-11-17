"""Pass the Inkscape document through unchanged for the native About dialog."""

import sys

sys.stdout.buffer.write(sys.stdin.buffer.read())
