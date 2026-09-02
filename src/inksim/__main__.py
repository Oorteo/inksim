# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Package entry point for ``python -m inksim``.

Running ``cli.py`` directly does not give it a package context, so its
relative imports (for example ``from .constants import ...``) cannot work.
Starting the package with ``python -m inksim`` makes Python load this module
as ``inksim.__main__`` and preserves that context.

This module deliberately contains no CLI logic.  It delegates to ``cli`` so
there is one implementation of ``main()`` for both ``python -m inksim`` and
the installed ``inksim`` console command.  Launchers may invoke this module
without changing the caller's working directory, so paths supplied by the
user keep their expected meaning.  The project launcher can use either its
``.venv`` Python interpreter when available or the system ``python3`` as a
fallback; both launch modes execute ``python -m inksim``.
"""

from .cli import main


main()