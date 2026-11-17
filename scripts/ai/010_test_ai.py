#!/usr/bin/env uvr
# SPDX-FileCopyrightText: 2026 Authors (see git history)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Send a prompt to GPT-6 Luna through the Copilot SDK."""

from __future__ import annotations

import argparse
import asyncio
import sys

from copilot import CopilotClient
from copilot.session_events import AssistantMessageData, AssistantUsageData, SessionEvent

MODEL_NAME = "GPT-6 Luna"


async def ask_copilot(prompt: str) -> str:
    usage_records: list[AssistantUsageData] = []

    def record_usage(event: SessionEvent) -> None:
        if isinstance(event.data, AssistantUsageData):
            usage_records.append(event.data)

    async with CopilotClient() as client:
        models = await client.list_models()
        model = next(
            (item for item in models if item.name.casefold() == MODEL_NAME.casefold()),
            None,
        )
        if model is None:
            available = ", ".join(item.name for item in models)
            raise RuntimeError(f"{MODEL_NAME} is unavailable. Available models: {available}")

        async with await client.create_session(model=model.id, available_tools=[]) as session:
            session.on(record_usage)
            response = await session.send_and_wait(prompt, timeout=120)

    if response is None or not isinstance(response.data, AssistantMessageData):
        raise RuntimeError("Copilot did not return an assistant message.")

    def total(field: str) -> int | None:
        values = [getattr(record, field) for record in usage_records]
        if not values or any(value is None for value in values):
            return None
        return sum(values)

    input_tokens = total("input_tokens")
    output_tokens = total("output_tokens")
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    print(
        f"Token usage across {len(usage_records)} model call(s): "
        f"input={input_tokens if input_tokens is not None else 'unavailable'}, "
        f"output={output_tokens if output_tokens is not None else 'unavailable'}, "
        f"total={total_tokens if total_tokens is not None else 'unavailable'}",
        file=sys.stderr,
    )
    return response.data.content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Reply with exactly: Copilot SDK works.",
        help="Prompt to send (default: a short connectivity test)",
    )
    args = parser.parse_args()
    print(asyncio.run(ask_copilot(args.prompt)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
