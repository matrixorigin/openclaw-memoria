#!/usr/bin/env python3
"""Verify that the OpenClaw plugin installs and loads in an isolated home."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ID = "memory-memoria"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _extract_json_document(raw: str) -> object:
    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(raw) if char in "[{"]
    best: tuple[int, object] | None = None
    for index in reversed(starts):
        suffix = raw[index:]
        chunk = suffix.lstrip()
        consumed_prefix = len(suffix) - len(chunk)
        try:
            value, end = decoder.raw_decode(chunk)
            consumed = consumed_prefix + end
            if best is None or consumed > best[0]:
                best = (consumed, value)
        except json.JSONDecodeError:
            continue
    if best is not None:
        return best[1]
    raise ValueError("Unable to find JSON payload in command output")


def _run(cmd: list[str], env: dict[str, str]) -> str:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)}: {message}")
    return proc.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plugin-path",
        default=str(REPO_ROOT),
        help="Path to the plugin repo or packed plugin directory.",
    )
    parser.add_argument(
        "--openclaw-home",
        default="",
        help="Optional isolated OPENCLAW_HOME. Defaults to a temp directory.",
    )
    args = parser.parse_args()

    openclaw_home = (
        Path(args.openclaw_home).expanduser().resolve()
        if args.openclaw_home
        else Path(tempfile.mkdtemp(prefix="openclaw-memoria-verify-"))
    )
    plugin_path = Path(args.plugin_path).expanduser().resolve()

    env = os.environ.copy()
    env["OPENCLAW_HOME"] = str(openclaw_home)

    install_output = _run(
        ["openclaw", "plugins", "install", "--link", str(plugin_path)],
        env,
    )
    list_output = _run(["openclaw", "plugins", "list", "--json"], env)
    payload = _extract_json_document(list_output)
    if isinstance(payload, dict):
        plugins = payload.get("plugins")
    else:
        plugins = payload
    if not isinstance(plugins, list):
        raise RuntimeError("Unexpected plugin list payload")

    plugin = next(
        (entry for entry in plugins if isinstance(entry, dict) and entry.get("id") == PLUGIN_ID),
        None,
    )
    if plugin is None:
        raise RuntimeError(f"Plugin {PLUGIN_ID!r} was not found after install")
    if plugin.get("status") != "loaded":
        raise RuntimeError(f"Plugin {PLUGIN_ID!r} is not loaded: {plugin.get('status')!r}")

    print(
        json.dumps(
            {
                "ok": True,
                "plugin_id": PLUGIN_ID,
                "status": plugin.get("status"),
                "openclaw_home": str(openclaw_home),
                "tools": plugin.get("toolNames", plugin.get("tools", [])),
                "services": plugin.get("services", []),
                "cliCommands": plugin.get("cliCommands", []),
                "install_output": install_output.strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
