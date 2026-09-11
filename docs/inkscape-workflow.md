# Inkscape / Ink/Stitch / InkSim workflow

## Contents

- [Calling InkSim from Inkscape](#calling-inksim-from-inkscape-after-the-pr-is-released)
- [Window layout and snap position](#window-layout-and-snap-position)
- [Export preview back to Inkscape](#export-preview-back-to-inkscape)
- [Tips](#tips)

InkSim can work as an external preview for the [Ink/Stitch](https://inkstitch.org/) extension, but this integration is **not available in the current official Ink/Stitch release**. It is currently being developed and reviewed as a pull request.

Until it is merged, start InkSim separately from a terminal as described in the [installation guide](installation.md), then paste your exported stitch files into InkSim manually.

> **Preliminary integration.** The menu path shown below does not exist in the official Ink/Stitch release yet. It is implemented on a development branch and will appear only after the corresponding PR is merged and released.

## Calling InkSim from Inkscape (after the PR is released)

Once the integration is available, select the objects you want to preview and choose:

**Extensions → Ink/Stitch → Visualize and Export → InkSim**

or press **Ctrl+"**.

<p align="center"><img src="assets/inkstitch/010_menu_inksim.webp" alt="InkSim menu in Inkscape" width="600"></p>

Ink/Stitch builds a stitch plan and forwards it to InkSim. The extension uses a small local IPC command, so InkSim can run in its own window independently of Inkscape.

## Window layout and snap position

When you work with Inkscape on one side and InkSim on the other, use **View → Save current snap position** to remember the InkSim window position and size. The next time Ink/Stitch opens InkSim, the window snaps back to that layout.

<p align="center"><img src="assets/inkstitch/020_save_snap.webp" alt="Save snap position menu" width="400"></p>

You can also toggle the layout quickly with **View → Snap window layout** (**M**) or clear the saved position from the same menu.

## Export preview back to Inkscape

After inspecting the design, copy the rendered preview back to Inkscape:

1. Choose **File → Export shaded PNG for print**.
2. Click **Copy to clipboard**.
3. Switch to Inkscape and press **Ctrl+V** to paste the image next to your vector design.

<p align="center"><img src="assets/inkstitch/020_export_image.webp" alt="Export preview and paste back into Inkscape" width="600"></p>

The pasted image is the full-resolution preview, so it keeps the same quality as the saved PNG.

## Tips

- Press **R**, **X**, **J**, **N**, **G**, **E**, **Z**, etc. to switch renderers and overlays.
- The **bottom view** (**E**) shows how the back of the embroidery would look.
