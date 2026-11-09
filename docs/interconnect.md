# InkSim Interconnect

## Contents

- [Single Server Process](#single-server-process)
- [Command Line](#command-line)
- [Protocol](#protocol)

InkSim uses one persistent background process, the singleton server, to own all
viewer windows. Other applications and scripts call `inksim` as usual. The
call is forwarded to the running server, which shows the file in the requested
window. Starting the server first makes later calls fast, because no new
viewer process is needed.

The transport is Qt `QLocalServer` and `QLocalSocket`. It works on Windows,
macOS, and Linux and does not open a TCP port. The endpoint name is per user,
so separate operating-system accounts run separate servers.

## Single Server Process

Start the server without a window:

```bash
uv run inksim --server
```

Calls to `inksim` while the server runs are forwarded to it:

- A call with a file opens the file in window `0` (or in the window given by
  `--index`).
- With `--new-window`, the server opens a new window for the file.
- Without a file and with no open windows, the server creates a window.

The server keeps the list of its windows in creation order. When window `0`
closes, the next window takes its place as index `0`.

Closing the last window leaves the server running for
`server_idle_timeout` seconds (default `300`). Set the value to `0` to keep
the server running until it is stopped explicitly. The timeout is set in the
InkSim configuration.

File -> Quit all windows & server closes every window and stops the server.

If the server's `app_version`, `protocol_version`, or `code_fingerprint` differs
from the `inksim` command being run, the new command asks the old server to
shut down and starts the new server. The fingerprint is a SHA-256 over the
package's `.py` sources, so it also catches edits that do not change the
version. Frozen builds are not supported yet and raise `NotImplementedError`. A
language change in the GUI closes all windows and reopens the current file in
a new process.

On Windows, `inksim-gui` remains the GUI entry point. The server and the
forwarding calls use the same `inksim` package.

## Command Line

| Option | Meaning |
| --- | --- |
| `--server` | Run the singleton server without a window |
| `--index N` | Send the file to window `N` (default `0`) |
| `--new-window` | Open a new window for the file |
| `--stop-server` | Close all windows and stop the running server |

Examples:

```bash
uv run inksim --server
uv run inksim tests/data/sample.pes
uv run inksim --index 1 tests/data/square.pes
uv run inksim --new-window tests/data/square.pes
uv run inksim --stop-server
```

If no server is running, a normal `inksim` call starts the GUI as before.
When a call asks for a server that cannot be reached, the command exits with a
non-zero code and prints the error.

## Protocol

Each message is one UTF-8 JSON object per line. Every request has a `type` and
a `protocol_version` (currently `2`). Every request receives one JSON response
line with `"ok": true` or `"ok": false` and an `error` text.

| Request `type` | Purpose | Success response fields |
| --- | --- | --- |
| `hello` | Version handshake | `app_version`, `code_fingerprint`, `protocol_version`, `windows` |
| `status` | Number of open windows | `windows` |
| `open` | Shows a file or creates a window (see fields below) | `index` of the window used |
| `shutdown` | Closes all windows and stops the server | none |

Fields of `open`:

- `index`: window index (default `0`); an index outside the list is an error.
- `new_window`: create a new window instead of reusing one. A window is also
  created when none is open.
- `path`: file to open. `null` only focuses the window. A directory opens the
  file dialog in that directory.
- `document_path`, `autoplay`, `delete_after_load`: as for the command line.
- `window`: options for newly created windows (fullscreen, size, position,
  snap layout). They do not change existing windows.

```json
{"type":"open","protocol_version":2,"index":0,"new_window":false,"path":"/absolute/path/design.pes"}
```

```json
{"ok": true, "index": 0}
```

Errors have `"ok": false` and an `error` text.
 are added to `InkSimServer._handle_request` in
`src/inksim/server.py` and documented here.
