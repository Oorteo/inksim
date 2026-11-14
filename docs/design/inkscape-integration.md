# Inkscape / Ink/Stitch Integration Design and TODO

Status: planning
Date: 2026-10-27

Implementation status (2026-10-27):

- New `OpenBrowserDialog` is the primary **File -> Open** action. The old
  embroidery-only dialog remains as **File -> Open embroidery**.
- The dialog detects Inkscape and Ink/Stitch from environment variables and
  `PATH`, shows what is missing, renders SVG thumbnails, previews embroidery
  files, converts SVG to CSV through Inkscape, and can launch a tagged
  Inkscape window for editing. Dropping an `.svg` on the window opens the same
  browser.
- Inkscape child processes use `clean_child_environment()` so the InkSim
  virtualenv cannot leak into Inkscape's extension interpreter.
- Not implemented yet: persistent sessions, selection-only preview, automatic
  refresh, request/response files, on-the-fly extension installation, and the
  standalone Ink/Stitch backend.

## Goal

Turn InkSim into the entry point for the embroidery design loop:

- `.svg` is the editable source file (Inkscape + Ink/Stitch).
- `.csv` is the generated stitch data used by the InkSim viewer.
- InkSim can open an `.svg`, offer "edit in Inkscape" or "preview", and
  generate the CSV through Ink/Stitch.
- InkSim can start and drive Inkscape when it is available.
- InkSim can work without Inkscape if a standalone Ink/Stitch runtime is
  available.

InkSim remains a viewer. It does not become an SVG editor and it does not
duplicate Ink/Stitch stitch generation.

## Non-goals

- Reimplementing Ink/Stitch stitch algorithms.
- Editing SVG content inside InkSim.
- Requiring Inkscape for normal embroidery-file viewing.
- Silently modifying the user's `.svg`.

## Decisions

These are the current design decisions. They take precedence over older
sections of this document.

1. **`--app-id-tag` is mandatory for managed Inkscape sessions.**
   InkSim must never send a shell command to "whatever Inkscape happens to be
   running". Every instance started by InkSim gets a unique tag, and every
   follow-up command carries that tag. This isolates the shell/action channel
   from other Inkscape windows and from other InkSim sessions.

2. **No local IPC in the new flow.**
   The Inkscape integration must not depend on the InkSim singleton server
   (see [interconnect.md](../interconnect.md)). The Qt `QLocalServer` used
   by that server is a separate feature. IPC for this flow is replaced by a
   private session directory with request and response files.

3. **The data flow starts and ends in InkSim.**
   InkSim creates a session directory, sets environment variables, launches
   Inkscape, and waits for result files. The extension (or Ink/Stitch
   subprocess) writes files back. No sockets, no named pipes, no queued
   messages.

4. **Selection-first preview.**
   When objects are selected in Inkscape, preview only the selection by
   default. An empty selection means the whole document. The user can override
   this in the preview action.

5. **InkSim owns its Inkscape extension.**
   A small `oorteo.inksim.*` extension is bundled with InkSim and installed into
   Inkscape's user extensions directory on demand. It is a thin orchestrator,
   not a fork of Ink/Stitch. It must not import Ink/Stitch internals, so no
   Ink/Stitch release is required for it to work.

6. **Minimise Ink/Stitch changes.**
   Ink/Stitch improvements are welcome, but v1 must work with an unmodified
   Ink/Stitch installation. Any new CLI helper is implemented in InkSim's
   wrapper first and proposed to Ink/Stitch only as an optional optimization.

7. **Never write into read-only extension directories.**
   Ink/Stitch installers may place their files in system-wide read-only
   directories. InkSim installs only into the writable user extension
   directory, with a manifest and version check, and never edits Ink/Stitch's
   own files.

8. **The open dialog is being replaced gradually.**
   The new file browser with previews is developed in parallel with the
   existing `EmbroideryOpenDialog` and selected by a setting until it is
   ready. The old dialog remains the fallback.

9. **Inkscape's extension interpreter is user-owned state.**
   `extensions/python-interpreter` in `preferences.xml` is a global Inkscape
   preference that every `.inx` declaring `interpreter="python"` uses (for
   example Ink/Stitch). InkSim's own `preview.inx` uses
   `<command location="absolute">` with the InkSim launcher, so it does not
   depend on that preference at all. InkSim therefore never rewrites it
   automatically: the Inkscape dialog only reports the current value and
   offers optional launchers (`uvr`, the Ink/Stitch virtualenv interpreter, a
   custom path) behind an explicit **Apply** with stored backup and
   **Restore previous**. `uvr` is genuinely useful only when several
   extensions each need their own Python environment; for a single Ink/Stitch
   installation a plain interpreter path is enough.

## Verified facts (2026-10-27)

Local environment: Inkscape 1.4.4, Ink/Stitch development extension linked into
`~/.config/inkscape/extensions/inkstitch-dev`.

1. Inkscape supports the options needed for this plan:

   ```bash
   inkscape --app-id-tag=TAG file.svg
   inkscape -q --active-window --app-id-tag=TAG ...
   inkscape --shell
   inkscape --actions="ACTION(:ARG);..."
   inkscape --action-list
   inkscape --user-data-directory
   inkscape --system-data-directory
   inkscape --export-type=csv --export-filename=FILE.csv
   ```

2. Installed Ink/Stitch extensions are exposed as Inkscape actions:

   ```text
   org.inkstitch.about
   org.inkstitch.simulator
   org.inkstitch.apply-palette
   ...
   ```

   They can be discovered with `inkscape --action-list` and invoked with
   `--actions`. Output extensions are different: `org.inkstitch.output.csv`
   is declared as `<output is_exported="true">`, not as an effect action.

3. Direct SVG to CSV conversion through Inkscape works without a GUI:

   ```bash
   inkscape --batch-process --export-type=csv \
     --export-filename=/tmp/design.csv design.svg
   ```

   A test with `src/inksim/assets/app_icons/inksim.svg` produced a valid CSV
   with 24,749 stitches and 7 thread colors. This is the most important
   supported path for the first implementation.

4. `--export-filename=-` is not a stdout stream for extension outputs. It
   created a file literally named `-`. Always use a real temporary path.

5. Some Inkscape actions produce machine-readable stdout:

   ```bash
   inkscape --batch-process --actions="query-all" file.svg
   inkscape --batch-process --actions="select-all;select-list" file.svg
   ```

   `query-all` prints CSV geometry rows and `select-list` prints object IDs.
   This is enough for basic document/selection inspection without an
   extension, but structured export and unsaved-document handling still use
   the InkSim extension. Extension effects are not guaranteed to print JSON.

6. Ink/Stitch can also be started outside Inkscape:

   ```bash
   INKSTITCH_OFFLINE_SCRIPT=1 \
     <python> /path/to/inkstitch/inkstitch.py \
     --extension=output --format=csv < design.svg > design.csv
   ```

   This needs a working Ink/Stitch Python environment. The current Ink/Stitch
   `pyproject.toml` has no console entry point, and a development `DEBUG.toml`
   may enable debuggers/profilers. A clean standalone CLI is a separate
   Ink/Stitch-side task.

7. Inkscape 1.4.4 does not expose a `file-save` action. To capture the current
   in-memory document, use `export-plain-svg` with `export-filename` and
   `export-do` to write a temporary snapshot. There is no need to save the
   user's document just to preview it.

8. `org.inkscape.extension.manager` is available as an action, but there is no
   documented "rescan extensions" action. A newly installed extension is
   normally picked up only by a new Inkscape launch.

9. Confirmed: `inkscape -q --app-id-tag=TAG ...` does not fall back to another
   Inkscape instance. If no instance with that tag exists, the command does not
   connect and exits. This is the required safety property: a tag mismatch must
   fail, never target a foreign window.

10. Confirmed: the InkSim `.inx` must be installed **before** the tagged
    Inkscape instance is launched. Installing it while Inkscape is running
    requires a restart of that instance.

11. Inkscape children must not inherit InkSim's virtualenv environment.
    Launching Inkscape from a `uv run` process with `VIRTUAL_ENV`/`PYTHONPATH`
    and the venv `bin` on `PATH` made the Ink/Stitch export hang (the
    extension's `python` resolved to the wrong interpreter). Stripping those
    variables and the venv `bin` from `PATH` fixed the export. Use
    `clean_child_environment()` for every Inkscape subprocess.

## Architecture

```text
InkSim (start)
  |
  | creates a private session directory, writes request.json,
  | exports INKSIM_SESSION_DIR / INKSIM_REQUEST_ID / token
  v
Inkscape --app-id-tag=inksim-<random> file.svg
  |
  | user edits, selects objects
  v
oorteo.inksim.bridge extension (inside Inkscape, same environment)
  |
  | writes snapshot.svg / selection.svg if needed
  | calls Ink/Stitch or Inkscape --export-type=csv
  v
session/response-<id>.json + preview-<id>.csv
  |
  | InkSim watches/waits for the response file
  v
InkSim (end) loads the CSV into the existing viewer
```

The same session protocol is used by headless conversion. Only the middle
step differs: InkSim can call `inkscape --export-type=csv` or a standalone
Ink/Stitch wrapper directly, with the same result directory contract.

### Session directory

```text
<runtime>/inksim-session-<uuid>/
    session.json           # version, tag, pid, source, token, capabilities
    request-<id>.json      # command, document, selection, output path
    response-<id>.json     # ok, error, result metadata
    preview-<id>.csv       # generated stitch data
    snapshot-<id>.svg      # optional copy of the current document
    selection-<id>.json    # optional selection IDs and bounds
    done-<id>              # atomic completion marker
    logs/                  # stderr tails, diagnostics
```

Rules:

- The directory is created with owner-only permissions (`0700`).
- Response files are written to a temporary name and atomically renamed.
- A random token in `session.json` and in the environment prevents stale or
  foreign requests from being accepted.
- InkSim does not trust paths from the request blindly; it validates that
  every output path is inside the session directory.
- Stale directories from crashed sessions are removed on startup when they are
  older than a configured age and have no live owner.


### Tool resolution

Resolution order for both tools:

1. Environment variable (`INKSCAPE_EXE`, `INKSTITCH_EXE`).
2. Explicit configuration in `config.toml`.
3. Auto-detection.
4. User prompt with a file picker.

Inkscape auto-detection:

- `shutil.which("inkscape")` on Linux.
- Standard install locations on Windows and macOS.
- Validate with `inkscape --version`.
- Probe `--app-id-tag`, `--export-type=csv`, and `--actions` support.

Ink/Stitch auto-detection:

- If Inkscape is available, inspect its user and system extension directories
  (`--user-data-directory`, `--system-data-directory`) and parse
  `inkstitch*about.inx` as the existing dialog already does.
- If no Inkscape, use `INKSTITCH_EXE`, config, or a known checkout/venv.
- Validate by running a small conversion or a version probe.

Proposed config:

```toml
[inkscape]
path = "/usr/bin/inkscape"

[inkstitch]
command = "uv run --project /path/to/inkstitch python inkstitch.py"
source_dir = "/path/to/inkstitch"

[integration]
svg_open_action = "ask"   # ask | preview | edit | edit_preview
auto_refresh = true
preferred_backend = "auto" # auto | inkscape | inkstitch
```

### Conversion backend matrix

| Inkscape | Ink/Stitch | Backend |
| --- | --- | --- |
| yes | inside Inkscape | `inkscape --export-type=csv` |
| yes | standalone only | snapshot active document, then Ink/Stitch headless |
| no | standalone | Ink/Stitch headless directly |
| no | no | clear error with install/configure instructions |

The first backend is preferred because Inkscape and Ink/Stitch already agree
on the executable environment.

### Inkscape session

A session represents one Inkscape instance started by InkSim:

- `tag = "inksim-<random>"`, unique per session.
- Launch: `inkscape --app-id-tag=<tag> <file>`.
- Set the session environment on the `Popen` call; the extension inherits it.
- Keep the `Popen` handle and the tag in `session.json`.
- Liveness: process handle first, then a platform process scan filtered by the
  tag.
- Execute one-shot commands with
  `inkscape -q --app-id-tag=<tag> --actions=...`.
- A persistent `--shell` connection is optional and only after the spike proves
  that it targets the tagged instance, survives document changes, and does not
  flood stdout. The file-based result protocol must work without it.

Important: `--shell` is never started without the tag. If the tag cannot be
matched, fail with a clear error instead of risking a command in the wrong
Inkscape window.

Do not adopt arbitrary Inkscape instances in v1. An adopted instance has no
session environment and cannot use the file protocol reliably. "Adopt" can be
added later through an explicit reconnect flow that asks the user to start a
tagged instance.

### InkSim Inkscape extension

A small extension bundled with InkSim provides a stable contract that does not
depend on Inkscape action details or Ink/Stitch internals.

Files:

```text
inksim-extension/
    inksim_bridge.inx
    inksim_bridge.py
    manifest.json
    VERSION
```

Extension ID namespace: `oorteo.inksim.bridge` (and future `oorteo.inksim.*` IDs).
Do not reuse `org.inkstitch.*` IDs; that namespace belongs to Ink/Stitch.

The extension is an `effect` extension because effects appear in the Inkscape
menu and in `--action-list`. It must not output an SVG to stdout; after
writing its result files it exits without letting Inkscape replace the
document.

Commands handled through the request file:

- `ping` - validate session, Inkscape version, and extension version.
- `info` - document path, document name, page size, selection IDs, bounds,
  Ink/Stitch presence.
- `snapshot` - write the current in-memory document to a temporary SVG,
  including unsaved changes.
- `export` - convert the current document or the current selection to CSV.
- `run_action` - invoke a curated Inkscape/Ink/Stitch action and report the
  result.

The extension is a **thin orchestrator**:

- It uses `inkex` only for reading and writing the document.
- It does not import Ink/Stitch modules.
- For conversion it either calls the installed Inkscape export extension
  (`inkscape --export-type=csv` on a snapshot) or a configured standalone
  Ink/Stitch command.
- If it needs to preserve selection context, it leaves the selection in the
  snapshot and asks Ink/Stitch to process it (for example with a selection
  file or an `--id` argument), rather than copying loose objects and losing
  document metadata.

Request/response protocol:

```json
{
  "version": 1,
  "id": "req-123",
  "token": "...",
  "command": "info | snapshot | export | run_action | ping",
  "document": "/path/to/design.svg",
  "output": "/session/preview-123.csv",
  "snapshot": "/session/snapshot-123.svg",
  "selection": "auto | all | ids",
  "ids": ["id1", "id2"],
  "action": "org.inkstitch.density-map"
}
```

```json
{
  "version": 1,
  "id": "req-123",
  "ok": true,
  "result": {
    "document": "/path/to/design.svg",
    "selection_count": 2,
    "stitch_count": 24749,
    "thread_count": 7,
    "output": "/session/preview-123.csv"
  },
  "error": null
}
```

Transport is deliberately only the file protocol:

1. InkSim writes `request-<id>.json` into the session directory.
2. InkSim invokes `oorteo.inksim.bridge` with the request ID as the action
   argument, or the extension finds the newest pending request in
   `INKSIM_SESSION_DIR`.
3. The extension writes `response-<id>.json` and `done-<id>` atomically.
4. InkSim waits with a timeout, reads the response, and loads the CSV.

No sockets, named pipes, or `inksim` server calls are used by the new flow.

### Selection preview

Ink/Stitch already processes `self.svg.selection` when a selection exists, and
the old custom extension relied on that. The new flow keeps the same semantic:

1. **Whole document** - no selection, or "Preview whole document" chosen.
2. **Current selection** - default when at least one object is selected.
3. **Explicit IDs** - used when InkSim has a stored selection but Inkscape is
   not currently focused on it.

Selection must preserve document context. Do not extract selected objects into
a bare SVG if that would drop layers, groups, thread palette, commands, or
document metadata. Prefer setting the selection in the full document and
letting Ink/Stitch resolve it. If selection-only conversion loses context, the
UI must warn and offer whole-document preview.

### On-the-fly extension installation

InkSim detects and installs its extension at startup or on first integration
use:

1. Resolve the writable user extension directory:
   `inkscape --user-data-directory` + `extensions`.
2. Compare `manifest.json` and `VERSION` with the bundled files.
3. If missing or outdated, install into a dedicated subdirectory, for example
   `<user-data>/extensions/inksim/`.
4. Never write into `--system-data-directory` or into Ink/Stitch's own
   directory. Those may be read-only and are not ours.
5. Verify that Inkscape can see the extension through `--action-list` after a
   restart or a new launch.
6. If the user directory is not writable, disable the extension-backed
   features and explain how to install manually. Do not silently fall back to
   a lower-fidelity path without telling the user.

Because Inkscape loads extensions at startup, a running instance will not see a
newly installed extension. InkSim must:

- install before launching a new tagged Inkscape instance, or
- ask the user to restart the tagged instance, or
- use the action-only fallback for the current instance.

There is an `org.inkscape.extension.manager` action but no documented
"rescan extensions" action. Restarting is the reliable path.

Do not overwrite files that InkSim does not own. If an old `inksim.inx` or a
foreign file with the same name exists, back it up or use a versioned
directory and report the conflict.


## User experience

### File -> Open browser (new dialog)

The current `EmbroideryOpenDialog` is a simple directory/file picker. The new
goal is a first-class browser with previews for every supported file type. It
is developed in parallel and selected by a setting:

```toml
[ui]
open_dialog = "classic"   # classic | browser
```

Requirements:

- Directory tree or breadcrumb navigation, recent directories, and favorites.
- List/grid view with thumbnails, file name, type, size, modified time, and
  stitch/thread counts when available.
- Large preview pane showing:
  - a rendered stitch preview for embroidery files,
  - a vector thumbnail and optional stitch preview for `.svg`,
  - a stitch preview and metadata for `.csv`,
  - a generic placeholder for unsupported files.
- Filter chips or a type filter, plus a text search field.
- Keyboard navigation: arrows, Enter to open, Space to preview, Esc to cancel.
- Multi-select where it makes sense; opening multiple files remains a separate
  feature.
- "Edit in Inkscape" action for `.svg` files, next to "Open" and "Preview".
- Background thumbnail generation with a bounded worker pool, cancellation
  when the selection changes, and disk caching.
- Thumbnail cache key: absolute path, size, mtime, and a renderer/version
  token. Store under the user cache directory, not in the source folder.
- No blocking of the UI while Inkscape or Ink/Stitch is running. Show a
  placeholder and a progress indicator, with a cancel option.
- Graceful degradation when Inkscape or Ink/Stitch is missing: show the vector
  thumbnail, disable stitch preview, and explain why.

Implementation options:

- A custom `QDialog` with `QFileSystemModel`, a custom proxy model for filters,
  `QTreeView`/`QListView`, and a preview pane. This gives full control.
- A non-native `QFileDialog` with a custom sidebar and preview widget. This
  keeps some platform behavior but is harder to extend.

Recommendation: custom dialog with a model/view architecture. Keep all
thumbnail and conversion work in worker threads and reuse the existing
embroidery preview code where possible.

### Opening an `.svg`

The open dialog and drag-and-drop handler must recognize `.svg`. The chooser:

- **Preview** (default): convert to a temporary CSV with Ink/Stitch and open it.
- **Edit in Inkscape**: launch a tagged Inkscape window.
- **Edit and preview**: launch Inkscape and load a preview.
- **Cancel**.

A "remember my choice" option stores `integration.svg_open_action`. A menu
entry and a command-line flag override the stored choice.

CLI:

```bash
inksim design.svg
inksim design.svg --svg-mode=preview
inksim design.svg --svg-mode=edit
inksim design.svg --svg-mode=ask
```

### Menu structure

`Integration`:

- Locate Inkscape / Ink/Stitch (status, versions, paths, test buttons).
- Open current document in Inkscape.
- Preview current document (whole document).
- Preview selection from Inkscape.
- Refresh preview from source.
- Toggle automatic refresh on save.
- Run Ink/Stitch action (curated list plus "run by ID").
- Install/update InkSim Inkscape extension.
- Show session/diagnostic information.

### Preview lifecycle

- Generation writes only to a temporary CSV.
- The source document path remains the authoritative `document_path` for Save
  As and export defaults.
- On success, the viewer loads the CSV and the title shows both the source SVG
  and the generated stitch counts.
- On failure, keep the previous preview and show the captured stderr tail.
- Clean per-request temporary files after completion or failure. Keep the
  session metadata and the last successful snapshot/CSV in the recovery cache
  until the TTL expires, so reconnect and diagnostics still work.
- A stale indicator appears when the SVG mtime is newer than the CSV.

### Refresh

The frame already reloads when the current file changes on disk. Extend it:

- Track the source `.svg` mtime, not only the generated CSV.
- If the source changed and auto-refresh is enabled, regenerate the CSV and
  reload.
- Debounce saves. Inkscape writes files in several steps, so wait for a stable
  mtime before converting.
- If Inkscape is running with unsaved changes, a file-based preview is stale by
  definition. Offer "Preview from Inkscape" when a session exists.

### Document and window lifecycle

Closing the edited document is a real problem, because Inkscape owns the
unsaved state. InkSim must never try to close, save, or recreate it
automatically.

Rules:

- InkSim never sends `window-close`, `file-close`, or a process kill to
  Inkscape. The user closes the document or the window.
- `window-close` is especially unsafe: Inkscape documents say it does not
  check for data loss. Do not expose it as a "cleanup" action.
- Closing the preview in InkSim only clears the viewer. It does not close the
  source document and does not close Inkscape.
- If the document is closed but Inkscape stays open, the tag still exists but
  there is no document. The extension reports `document_open=false`. InkSim
  marks the session `document_closed`, keeps the last preview, and offers
  "Reopen in Inkscape".
- If another document is opened in the same tagged instance, the reported
  document path changes. InkSim must not silently replace the preview; mark
  the session `document_changed` and ask whether to switch or detach.
- If Inkscape exits, the tag disappears. InkSim marks the session
  `inkscape_gone`, keeps the last preview, and cleans temp files after a TTL.
- If a request is pending when the document or Inkscape closes, no response
  arrives. InkSim times out, keeps the previous preview, and explains that
  Inkscape closed before finishing.
- If InkSim exits, Inkscape is left running. Session metadata is persisted and
  the session becomes `detached`; the next InkSim start can offer reconnect.
  Do not delete a session directory while Inkscape may still write to it.
- Unsaved Inkscape edits cannot be recovered after a crash. Keep the last
  successful snapshot and CSV in a recovery cache, but do not claim to recover
  unsaved edits.
- Never auto-save the user's document. A snapshot for preview is a separate
  temporary file and must not touch the source `.svg`.
- If the user wants to close Inkscape, they close it in Inkscape and get the
  normal save prompt. InkSim can focus or list its tagged windows, but it must
  not close them programmatically.

State model:

```text
starting -> ready -> busy -> ready
ready -> document_closed -> (reopen) starting
ready -> document_changed -> (switch/detach) ready
ready/busy -> inkscape_gone -> stale
ready -> detached (InkSim exit) -> reconnect -> ready
```

Reconnect after an InkSim restart:

- Session metadata lives in a per-user state directory, for example
  `QStandardPaths.AppDataLocation / sessions / <id> / session.json`.
- On startup, scan the state directory and check the tag against running
  processes.
- If the tagged Inkscape is alive, offer "Reconnect to Inkscape session for
  `<document>`". Reconnect uses the same file protocol; the environment in the
  Inkscape process still points to the session directory.
- If the tag is gone, mark the session `stale`, keep the last preview, and
  clean up according to the TTL policy.
- Never reconnect automatically to an untagged Inkscape instance.

## Module layout

```text
src/inksim/integration/
    __init__.py
    paths.py          # installations, resolvers, version/feature probes
    process.py        # subprocess helpers, timeouts, platform flags
    inkstitch.py      # headless Ink/Stitch runner and result parsing
    inkscape.py       # Inkscape exporter and session management
    session.py        # session directory, env, request/response files
    extension.py      # bundled extension install/update/version detection
    preview.py        # backend selection, temp files, orchestration
    errors.py         # typed errors and user-facing messages

src/inksim/extension/ # bundled into the wheel as package data
    inksim_bridge.inx
    inksim_bridge.py
    manifest.json
    VERSION

src/inksim/gui/
    inkscape_dialog.py   # rewritten status/configuration dialog
    svg_open_dialog.py   # preview / edit / both chooser
    open_browser.py      # new File -> Open browser with thumbnails
    thumbnail_cache.py   # disk cache and background rendering
```

Keep detection and subprocess logic out of Qt widgets so it is testable
without a GUI. Locate the bundled extension with `importlib.resources`, not
with a path relative to the source checkout, so `uv tool install` and wheels
work.

## Milestones

### M0 - Spikes (before code)

- [x] Tag isolation: `-q --app-id-tag=A` cannot affect instance `B`.
      Confirmed: with no instance for a tag, the command does not connect and
      exits instead of falling back to another Inkscape.
- [x] `-q --active-window` targeting with a tag. Covered by the same
      confirmation; add a two-instance regression test later.
- [ ] Verify `--shell` with a tag: lifetime, stdout, and wrong-instance
      behavior.
- [ ] Verify environment propagation from InkSim to Inkscape to an extension.
- [ ] Verify export of the active document including unsaved changes.
- [ ] Verify whole-document and selection-only CSV export.
- [ ] Verify snapshot of the active document with `export-plain-svg`.
- [ ] Verify that an extension can receive a request path through an action
      argument or through an environment variable.
- [x] On-the-fly installation into the user extensions directory requires a
      new Inkscape launch. Confirmed: install the `.inx` before starting the
      tagged instance.
- [ ] Verify document-close behavior: document closed while Inkscape stays
      open; Inkscape exits while a request is pending; session reconnect after
      an InkSim restart.
- [ ] Verify standalone `inkstitch.py` conversion through an InkSim wrapper,
      with no Ink/Stitch source changes.
- [ ] Record the results in this document.

### M1 - Tool resolution, config, and extension status

- [ ] Add `integration.paths` with `InkscapeInstallation` and
      `InkStitchInstallation`.
- [ ] Implement ENV > config > auto-detect precedence.
- [ ] Cache validated paths and versions in `config.toml`.
- [ ] Probe features: `--app-id-tag`, `--export-type=csv`, `--actions`.
- [ ] Detect the user and system extension directories and their writability.
- [ ] Detect bundled extension version, installed version, and conflicts.
- [ ] Rewrite the Inkscape dialog with status, versions, paths, and tests.
- [ ] Add unit tests with fake executables.

### M2 - New File -> Open browser (parallel rollout)

- [ ] Add the `ui.open_dialog` setting with `classic` and `browser` values.
- [ ] Build the browser shell: navigation, list/grid, filters, search, preview
      pane, keyboard handling.
- [ ] Add thumbnail cache and background rendering.
- [ ] Add embroidery thumbnails and metadata.
- [ ] Add SVG vector thumbnails and optional stitch previews.
- [ ] Add CSV thumbnails and metadata.
- [ ] Add graceful placeholders for unsupported or unreadable files.
- [ ] Keep the classic dialog as the default until the browser is stable.
- [ ] Add tests for filtering, selection, cache keys, and cancellation.

### M3 - SVG open flow

- [ ] Recognize `.svg` in the open dialog, CLI, and drag-and-drop.
- [ ] Add the preview/edit/both chooser and the remembered preference.
- [ ] Add `--svg-mode`.
- [ ] Map missing-tool errors to actionable dialogs.
- [ ] Add tests for the chooser and routing.

### M4 - Preview conversion

- [ ] Implement `InkscapeExporter` using `--export-type=csv`.
- [ ] Implement `InkStitchHeadlessExporter` for the no-Inkscape case.
- [ ] Run conversion off the GUI thread with progress and cancellation.
- [ ] Use private temporary files and clean them reliably.
- [ ] Parse stitch/thread counts for the title and status bar.
- [ ] Keep the previous preview on failure and show the stderr tail.
- [ ] Add integration tests with fake binaries and one optional real test.

### M5 - Inkscape session and selection

- [ ] Implement `InkscapeSession` and the tag lifecycle.
- [ ] Create the private session directory and set the environment.
- [ ] Implement liveness checks by tag and process handle.
- [ ] Distinguish `ready`, `document_closed`, `inkscape_gone`, `detached`, and
      `stale` states.
- [ ] Persist session metadata and offer reconnect after an InkSim restart.
- [ ] Handle a pending request timing out when the document or Inkscape closes.
- [ ] Never send close or kill commands to Inkscape.
- [ ] Launch/edit/open-current-document actions.
- [ ] Snapshot the active document to a temporary SVG.
- [ ] Query selection with `select-list` and export only the selection.
- [ ] Handle empty selection, groups, layers, and hidden objects.
- [ ] Add session tests with a fake Inkscape process.

### M6 - InkSim Inkscape extension and file protocol

- [ ] Implement `oorteo.inksim.bridge` with `ping`, `info`, `snapshot`, `export`,
      and `run_action`.
- [ ] Implement request/response files with atomic writes and timeouts.
- [ ] Implement install/update/version detection and conflict handling.
- [ ] Never write into read-only or Ink/Stitch-owned directories.
- [ ] Add a restart hint for an already-running Inkscape.
- [ ] Add security checks for private temp paths, tokens, and request IDs.
- [ ] Add tests with a fake extension and malformed responses.

### M7 - Live workflow and polish

- [ ] Extend reload-on-change from CSV to source SVG.
- [ ] Debounce Inkscape saves and handle atomic saves.
- [ ] Add stale/preview-source indicators.
- [ ] Add recent SVG files and a backend indicator.
- [ ] Add diagnostics: versions, paths, last command, stderr tail.
- [ ] Add i18n strings and update the user docs.
- [ ] Add screenshots of the new browser, chooser, and session status.

### M8 - Packaging and release

- [ ] Include the extension files as package data and locate them with
      `importlib.resources`.
- [ ] Document Inkscape/Ink/Stitch installation and ENV overrides.
- [ ] Add a sample SVG and CSV fixture for tests.
- [ ] Add CI coverage that skips real-tool tests when tools are absent.
- [ ] Verify Windows and macOS paths, spaces, unicode, and process handling.
- [ ] Keep Ink/Stitch changes optional; propose a CLI helper only if the
      wrapper approach is insufficient.

## Test plan

Unit tests:

- Path resolution and precedence.
- Command construction for every backend.
- Version/feature probe parsing.
- Error mapping (missing tool, non-zero exit, timeout, invalid CSV).
- Session directory creation, permissions, atomic writes, and cleanup.
- Request token validation and path traversal rejection.
- Temp file lifecycle.
- Session tag generation and liveness parsing.
- Extension manifest/version comparison and conflict detection.
- Open-browser filters, cache keys, and cancellation.

Integration tests with fake executables:

- A fake `inkscape` that prints version/data directories and writes a known
  CSV.
- A fake `inkstitch.py` that reads stdin and writes a known CSV.
- A fake process that hangs, to test timeouts and cancellation.
- A fake extension that writes valid, invalid, and late responses.
- Assert exact argv, `stdin`, `stdout`, environment, and platform flags.
- Test paths with spaces and non-ASCII characters.

Optional real-tool tests (skipped when tools are absent):

- Convert a fixture SVG with Inkscape + Ink/Stitch.
- Convert the same fixture with standalone Ink/Stitch.
- Convert only a selection and verify the stitch count is smaller.
- Compare stitch and thread counts with `pystitch`.
- Launch two tagged Inkscape instances and verify command isolation.
- Snapshot an unsaved active document and convert the snapshot.
- Install the bundled extension into a temporary user profile and verify it
  appears in `--action-list`.

Manual acceptance:

1. Open an `.svg` and choose Preview with only Inkscape installed.
2. Open an `.svg` and choose Preview with only standalone Ink/Stitch.
3. Choose Edit in Inkscape; the tagged window opens and can be queried.
4. Start a second tagged Inkscape window; preview must affect only the right
   instance.
5. Select part of the design and preview only the selection.
6. Edit without saving, then preview from Inkscape; unsaved changes appear.
7. Edit and save in Inkscape; the file-based preview refreshes.
8. Close the document but leave Inkscape open; InkSim keeps the last preview
   and offers "Reopen in Inkscape".
9. Close InkSim while Inkscape is open; reopen InkSim and reconnect to the
   detached session.
10. Close Inkscape while a preview request is running; InkSim times out
    cleanly and keeps the previous preview.
11. Try a missing tool, an invalid SVG, and a read-only extension directory;
    all show useful errors.
12. Browse files in the new open dialog; thumbnails load without blocking and
    are reused from cache.
13. Verify no source files are modified and no temp files remain.

## Additional considerations

These are easy to forget and should be tracked before the first release.

### Process and window lifecycle

- Do not kill Inkscape when InkSim exits. The user may still be editing.
- Do not send `window-close` or `file-close`; closing the edited document is
  always the user's decision.
- Offer "Show/focus Inkscape windows started by InkSim", not a programmatic
  close. Inkscape must show its own save prompt.
- Persist session metadata so InkSim can reconnect to a still-running tagged
  Inkscape after a restart. Mark the session `detached` while InkSim is away.
- Launch Inkscape with `clean_child_environment()`: strip `VIRTUAL_ENV`,
  `PYTHONPATH`, `PYTHONHOME`, and the venv `bin`/`Scripts` entries from
  `PATH`. Otherwise Ink/Stitch can pick the wrong `python` and hang.
- Detect `document_closed` (tag alive, no document) separately from
  `inkscape_gone` (tag gone).
- Reap child processes and avoid zombies; never leave a `--shell` process
  running after its session ends.
- Handle Inkscape crashing or being closed while a request is pending; time
  out, keep the previous preview, and explain what happened.
- Handle multiple InkSim windows and multiple tagged Inkscape instances.
- Do not adopt arbitrary Inkscape instances in v1; they lack the session
  environment.
- Keep the last successful snapshot and CSV in a recovery cache, but do not
  promise recovery of unsaved Inkscape edits after a crash.

### Document state

- There is no documented `file-save` action. Use `export-plain-svg` to a
  temporary snapshot to capture unsaved changes.
- Do not mark the user's document dirty just to preview it.
- Do not auto-save the document when InkSim exits or when the session is
  detached.
- If the user closes the document with unsaved changes, Inkscape shows its
  normal save prompt; InkSim must not interfere.
- After a document is closed, keep the last preview and offer "Reopen in
  Inkscape" using the last known path.
- Restore the previous selection after selection-only preview if the extension
  changed it.
- Warn when selection-only preview would lose document context (palette,
  commands, layer settings).
- Handle documents that were never saved and have no path.
- Handle multiple open documents in one Inkscape instance; identify the active
  document explicitly.
- Handle external changes to the file while Inkscape has unsaved edits.

### Extension installation

- Inkscape loads extensions at startup; there is no documented rescan action.
  Install before launch or ask for a restart.
- The `org.inkscape.extension.manager` action exists, but do not rely on it as
  a rescan mechanism.
- Detect writable user and read-only system directories.
- Never modify Ink/Stitch-owned files or system directories.
- Handle an existing `inksim.inx`, a broken symlink, or a foreign file with
  the same name.
- Include a manifest/version and support clean update and uninstall.
- Verify the extension appears in `--action-list` after installation.
- If installation is impossible, degrade to action/export-only mode with a
  clear explanation.

### Open dialog and thumbnails

- Thumbnail generation can be slow and memory-hungry; use a bounded pool,
  cancellation, and a disk cache.
- Cache keys must include mtime, size, and renderer/version; handle file
  replacement and atomic saves.
- SVG thumbnails via Inkscape are accurate but slow; a Qt vector thumbnail can
  be shown first and replaced later.
- Do not launch Inkscape once per file in a directory. Batch or defer.
- Handle network paths, permission errors, huge directories, and unicode
  names.
- Keep the classic dialog available until the browser passes manual testing.
- Decide whether the browser shows unsupported files or hides them by default.
- Provide a clear empty state and error state.

### Cross-platform

- `--app-id-tag` and `--active-window` behavior may differ on Windows and
  macOS; test each platform.
- Use `CREATE_NO_WINDOW`/`STARTUPINFO` on Windows for probes, but a visible
  window for editing.
- Process discovery must work without `pgrep` on Windows.
- Handle spaces, unicode, long paths, and UNC paths.
- Use owner-only ACLs/permissions for the session directory.
- Do not assume a writable home directory; handle managed/portable installs.

### Security and robustness

- Validate every path from a request against the session directory.
- Use a random token; reject stale or foreign requests.
- Do not use `shell=True`; build argument lists.
- Treat SVG/CSV content as untrusted input.
- Limit response file size and timeout to avoid hangs.
- Clean stale session directories without deleting active ones.
- Log the exact command, environment keys (not secrets), durations, and exit
  codes for diagnostics.

### Compatibility

- Test Inkscape 1.2, 1.3, and 1.4; degrade gracefully when an option or action
  is missing.
- Test Ink/Stitch stable and development installations.
- CSV headers and metadata may change; parse defensively and keep the raw
  file for debugging.
- The `.inx` schema and extension API can differ between Inkscape versions.
- The bundled extension must be included in the wheel and located with
  `importlib.resources`.

### Product and UX

- Do not hijack `.svg` file associations by default; offer "Open with InkSim".
- Explain the difference between "preview saved file" and "preview from
  Inkscape".
- Show which backend produced the preview.
- Make cancellation and progress visible for long conversions.
- Provide a "Copy diagnostics" button for support.
- Localize all new strings.
- Document the environment variables and the session directory.

## Risks and open questions

- Does `--app-id-tag` isolate `-q --active-window` and `--shell` identically on
  Windows and macOS?
- Does `--shell` return useful output, or only query/selection results?
- Can an extension action receive a request path reliably across Inkscape
  versions?
- Does selection-only export preserve thread palette, commands, and layer
  context?
- How do we best capture an unsaved document without a `file-save` action?
- How much of Ink/Stitch must be installed for standalone conversion, and how
  do we point to it without requiring a source checkout?
- Ink/Stitch development `DEBUG.toml` can attach debuggers and write logs;
  standalone conversion must use a clean runtime.
- Extension installation may require an Inkscape restart; how do we make that
  acceptable in the workflow?
- Inkscape extension directories may be symlinks, read-only, or managed by an
  installer; installation must be defensive.
- Large designs can take seconds or minutes to convert; progress and
  cancellation are mandatory.
- The new open dialog may become a large feature on its own; keep it behind a
  setting and ship it incrementally.
- Unsaved Inkscape edits cannot be recovered after a crash; only the last
  successful snapshot/CSV is recoverable.
- Session directories must outlive an InkSim exit so reconnect is possible,
  but stale directories must not accumulate forever.
- Reconnect must verify the tag, process owner, and token; never reconnect to
  a foreign Inkscape or another user's session.
- Closing the edited document is controlled by Inkscape, not InkSim; the UI
  must explain when the preview is older than the document state.

## Definition of done

- A user can open an `.svg`, preview it, and edit it in Inkscape without
  manually exporting a CSV.
- Selection-only preview works and preserves document context.
- The tagged session cannot affect another Inkscape instance.
- Closing InkSim never kills Inkscape; reopening InkSim can reconnect to the
  still-running tagged session.
- Closing the document or Inkscape never destroys the last preview; InkSim
  reports `document_closed` or `inkscape_gone` and offers a clear next step.
- InkSim never auto-saves or auto-closes the user's document.
- Both backends work or fail with a clear, actionable message.
- The bundled extension installs into the writable user directory and never
  touches read-only or Ink/Stitch-owned files.
- The source SVG is never modified.
- The preview refreshes predictably after edits.
- The new open dialog can be enabled and disabled without breaking the classic
  workflow.
- Existing embroidery-file workflows are unchanged.
- `uv run poe check` and `uv run poe test` pass.
