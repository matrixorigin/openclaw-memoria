#!/usr/bin/env python3
"""Verify plugin capability coverage and compatibility surface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PLUGIN_ID = "memory-memoria"
EXPECTED_TOOLS = [
    "memory_search",
    "memory_get",
    "memory_store",
    "memory_retrieve",
    "memory_recall",
    "memory_list",
    "memory_stats",
    "memory_profile",
    "memory_correct",
    "memory_purge",
    "memory_forget",
    "memory_health",
    "memory_observe",
    "memory_governance",
    "memory_consolidate",
    "memory_reflect",
    "memory_extract_entities",
    "memory_link_entities",
    "memory_entities",
    "memory_rebuild_index",
    "memory_capabilities",
    "memory_snapshot",
    "memory_snapshots",
    "memory_rollback",
    "memory_branch",
    "memory_branches",
    "memory_checkout",
    "memory_branch_delete",
    "memory_merge",
    "memory_diff",
]
EXPECTED_CLI_COMMANDS = ["memoria", "ltm"]
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
        cwd=REPO_ROOT,
        env=env,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)}: {message}")
    return proc.stdout


def _build_config() -> dict[str, Any]:
    return {}


def _mutate_config(config_path: Path, python_executable: str, db_url: str) -> None:
    config = json.loads(config_path.read_text())
    plugins = config.setdefault("plugins", {})
    allow = plugins.setdefault("allow", [])
    if isinstance(allow, list) and PLUGIN_ID not in allow:
        allow.append(PLUGIN_ID)
    elif not isinstance(allow, list):
        plugins["allow"] = [PLUGIN_ID]

    slots = plugins.setdefault("slots", {})
    if isinstance(slots, dict):
        slots["memory"] = PLUGIN_ID
    else:
        plugins["slots"] = {"memory": PLUGIN_ID}

    entries = plugins.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        plugins["entries"] = entries

    entries[PLUGIN_ID] = {
        "enabled": True,
        "config": {
            "backend": "embedded",
            "pythonExecutable": python_executable,
            "dbUrl": db_url,
            "defaultUserId": "coverage-user",
            "autoRecall": True,
            "autoObserve": False,
        },
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))


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
    parser.add_argument(
        "--python-executable",
        default=str(REPO_ROOT / ".venv" / "bin" / "python"),
        help="Python executable for the embedded plugin config.",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get(
            "MEMORIA_DB_URL",
            "mysql+pymysql://root:111@127.0.0.1:6001/memoria",
        ),
        help="MatrixOne DSN written into the isolated plugin config.",
    )
    args = parser.parse_args()

    plugin_path = Path(args.plugin_path).expanduser().resolve()
    openclaw_home = (
        Path(args.openclaw_home).expanduser().resolve()
        if args.openclaw_home
        else Path(tempfile.mkdtemp(prefix="openclaw-memoria-coverage-"))
    )
    state_dir = openclaw_home / ".openclaw"
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "openclaw.json"
    config_path.write_text(json.dumps(_build_config(), ensure_ascii=False, indent=2))

    env = os.environ.copy()
    env["OPENCLAW_HOME"] = str(openclaw_home)

    _run(["openclaw", "plugins", "install", "--link", str(plugin_path)], env)
    _mutate_config(config_path, args.python_executable, args.db_url)
    _run(["openclaw", "plugins", "enable", PLUGIN_ID], env)

    list_output = _run(["openclaw", "plugins", "list", "--json"], env)
    payload = _extract_json_document(list_output)
    plugins = payload.get("plugins") if isinstance(payload, dict) else payload
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

    tool_names = plugin.get("toolNames", plugin.get("tools", []))
    cli_commands = plugin.get("cliCommands", [])
    missing_tools = sorted(set(EXPECTED_TOOLS) - set(tool_names or []))
    missing_commands = sorted(set(EXPECTED_CLI_COMMANDS) - set(cli_commands or []))
    if missing_tools:
        raise RuntimeError(f"Missing tool registrations: {', '.join(missing_tools)}")
    if missing_commands:
        raise RuntimeError(f"Missing CLI commands: {', '.join(missing_commands)}")

    capabilities_output = _run(["openclaw", "memoria", "capabilities"], env)
    capabilities = _extract_json_document(capabilities_output)
    if not isinstance(capabilities, dict):
        raise RuntimeError("Unexpected capabilities payload")

    backend_features = capabilities.get("backendFeatures")
    if not isinstance(backend_features, dict):
        raise RuntimeError("Capabilities payload is missing backendFeatures")

    for field in ("rollback", "branches", "governance", "reflect", "entities", "rebuildIndex"):
        if not backend_features.get(field):
            raise RuntimeError(f"Expected backendFeatures.{field} to be true")

    aliases = capabilities.get("aliases")
    if not isinstance(aliases, dict) or aliases.get("memory_recall") != "memory_retrieve":
        raise RuntimeError("Capabilities payload is missing memory_recall alias mapping")

    result = {
        "ok": True,
        "plugin_id": PLUGIN_ID,
        "status": plugin.get("status"),
        "openclaw_home": str(openclaw_home),
        "tool_count": len(tool_names or []),
        "tools": tool_names,
        "cliCommands": cli_commands,
        "capabilities": capabilities,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
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
