# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

from inksim import debug


def test_configure_logging_overwrites_previous_log(tmp_path):
    log_path = tmp_path / "inksim.log"
    log_path.write_text("old run\n", encoding="utf-8")
    previous_handlers = set(debug.logger.handlers)
    previous_enabled = debug._debug_enabled
    previous_file_handler = debug._file_handler
    previous_log_path = debug._log_path

    try:
        debug.configure_logging(True, log_path)
        debug.logger.debug("new run")
        for handler in debug.logger.handlers:
            handler.flush()

        contents = log_path.read_text(encoding="utf-8")
        assert "old run" not in contents
        assert "new run" in contents
    finally:
        for handler in set(debug.logger.handlers) - previous_handlers:
            debug.logger.removeHandler(handler)
            handler.close()
        debug._debug_enabled = previous_enabled
        debug._file_handler = previous_file_handler
        debug._log_path = previous_log_path
