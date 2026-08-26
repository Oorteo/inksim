#!/usr/bin/env uvr
"""Send one local JSON command to a running InkSim server."""

import argparse
import json
import sys

from PySide6.QtWidgets import QApplication

from inksim.interconnect import send_command


def main():
    parser = argparse.ArgumentParser(description="Control a running InkSim server")
    subparsers = parser.add_subparsers(dest="command", required=True)
    open_parser = subparsers.add_parser("open", help="Open an embroidery file")
    open_parser.add_argument("path")
    open_del_parser = subparsers.add_parser(
        "open_and_delete",
        help="Open an embroidery file and delete it after loading",
    )
    open_del_parser.add_argument("path")
    subparsers.add_parser("focus", help="Focus the InkSim window")
    subparsers.add_parser("show", help="Show and focus the InkSim window")
    subparsers.add_parser("hide", help="Hide the InkSim window")
    subparsers.add_parser("quit", help="Quit the InkSim server")
    args = parser.parse_args()
    QApplication.instance() or QApplication([])
    command = {"command": args.command}
    if args.command in ("open", "open_and_delete"):
        command["path"] = args.path
        command["focus"] = True
    try:
        response = send_command(command)
    except RuntimeError as ex:
        print(str(ex), file=sys.stderr)
        return 1
    print(json.dumps(response))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())