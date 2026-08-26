# InkSim Interconnect

InkSim can expose a local control endpoint for external applications such as
Ink/Stitch. The endpoint uses Qt `QLocalServer` and `QLocalSocket`, so it does
not open a TCP port or require network access.

## Start The Server

Start a persistent InkSim GUI with:

```bash
uv run inksim --server
```

A file can be opened at startup:

```bash
uv run inksim --server tests/data/sample.pes
```

When `--server` is used, closing the main window hides it instead of stopping
the process. Use File -> Quit, the `quit` command, or terminate the process to
exit completely.

If another InkSim server is already running, a second command forwards its
file argument to the existing instance and exits:

```bash
uv run inksim --server tests/data/square.pes
```

## Client Script

The small Qt client is available for integration testing:

```bash
uv run python scripts/client/010_inksim_client.py open tests/data/sample.pes
uv run python scripts/client/010_inksim_client.py focus
uv run python scripts/client/010_inksim_client.py show
uv run python scripts/client/010_inksim_client.py hide
uv run python scripts/client/010_inksim_client.py quit
```

The client returns a non-zero exit code when no server is running or the
server rejects a command.

## Protocol

The socket carries one UTF-8 JSON object per line. The default endpoint name is
`inksim-local`.

Open a file and focus the window:

```json
{ "command": "open", "path": "/absolute/path/design.pes", "focus": true }
```

Other commands:

```json
{"command":"focus"}
{"command":"show","focus":true}
{"command":"hide"}
{"command":"quit"}
```

Every command receives one JSON response line:

```json
{ "ok": true, "command": "open", "path": "/absolute/path/design.pes" }
```

Errors have the form:

```json
{ "ok": false, "error": "..." }
```

The protocol is intentionally small. New commands should be added to
`inksim.interconnect.InterconnectServer._dispatch` and documented here.
Commands should remain local and idempotent where possible so wxPython,
PySide6, and future clients can use the same endpoint.
