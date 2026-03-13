#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ID="memory-memoria"
DEFAULT_INSTALL_DIR="${HOME}/.local/share/openclaw-plugins/openclaw-memoria"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OPENCLAW_HOME_VALUE="${OPENCLAW_HOME:-}"
SOURCE_DIR=""
KEEP_SOURCE=false

log() {
  printf '[memory-memoria] %s\n' "$*"
}

fail() {
  printf '[memory-memoria] error: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

usage() {
  cat <<'EOF'
Remove the OpenClaw Memoria plugin and its OpenClaw config.

Usage:
  bash scripts/uninstall-openclaw-memoria.sh [options]
  curl -fsSL <raw-script-url> | bash -s --

Options:
  --source-dir <path>  Also delete this plugin checkout after uninstall.
  --keep-source        Keep the managed install directory on disk.
  --help               Show this help text.

Environment overrides:
  OPENCLAW_HOME        Optional target OpenClaw home.
  PYTHON_BIN           Default: python3

What gets removed by default:
  - plugins.entries["memory-memoria"]
  - stale plugins.entries["\"memory-memoria\""] from older installers
  - plugins.installs["memory-memoria"]
  - plugins.allow entry for memory-memoria
  - plugins.load.paths entries that point at this plugin
  - managed companion skills in ~/.openclaw/skills: memoria-memory, memoria-recovery
  - the default managed plugin dir: ~/.local/share/openclaw-plugins/openclaw-memoria

What gets restored:
  - plugins.slots.memory -> memory-core
  - plugins.entries["memory-core"].enabled -> true

To also delete a custom checkout used with --source-dir during install:
  bash scripts/uninstall-openclaw-memoria.sh --source-dir /path/to/openclaw-memoria
EOF
}

config_file_path() {
  if [[ -n "${OPENCLAW_HOME_VALUE}" ]]; then
    printf '%s/.openclaw/openclaw.json' "${OPENCLAW_HOME_VALUE}"
  else
    printf '%s/.openclaw/openclaw.json' "${HOME}"
  fi
}

skills_dir_path() {
  if [[ -n "${OPENCLAW_HOME_VALUE}" ]]; then
    printf '%s/.openclaw/skills' "${OPENCLAW_HOME_VALUE}"
  else
    printf '%s/.openclaw/skills' "${HOME}"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-dir)
      SOURCE_DIR="${2:?missing value for --source-dir}"
      shift 2
      ;;
    --keep-source)
      KEEP_SOURCE=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

need_cmd "$PYTHON_BIN"

CONFIG_FILE="$(config_file_path)"

UNINSTALL_RESULT="$(
  UNINSTALL_CONFIG_FILE="${CONFIG_FILE}" \
  UNINSTALL_PLUGIN_ID="${PLUGIN_ID}" \
  UNINSTALL_DEFAULT_INSTALL_DIR="${DEFAULT_INSTALL_DIR}" \
  UNINSTALL_SOURCE_DIR="${SOURCE_DIR}" \
  UNINSTALL_KEEP_SOURCE="${KEEP_SOURCE}" \
  "$PYTHON_BIN" - <<'PY'
import json
import os
import shutil
import sys
from pathlib import Path


def resolve_text_path(raw: str) -> str:
    return str(Path(raw).expanduser().resolve())


def plugin_id_for_path(raw: str) -> str | None:
    path = Path(raw).expanduser()
    manifest = path / "openclaw.plugin.json"
    if not manifest.exists():
        return None
    try:
        payload = json.loads(manifest.read_text())
    except Exception:
        return None
    plugin_id = payload.get("id")
    return plugin_id if isinstance(plugin_id, str) else None


config_path = Path(os.environ["UNINSTALL_CONFIG_FILE"]).expanduser()
plugin_id = os.environ["UNINSTALL_PLUGIN_ID"]
default_install_dir = resolve_text_path(os.environ["UNINSTALL_DEFAULT_INSTALL_DIR"])
source_dir_raw = os.environ.get("UNINSTALL_SOURCE_DIR", "").strip()
keep_source = os.environ.get("UNINSTALL_KEEP_SOURCE", "false").lower() == "true"

data: dict[str, object]
if config_path.exists():
    data = json.loads(config_path.read_text())
else:
    data = {}

plugins = data.get("plugins")
if not isinstance(plugins, dict):
    plugins = {}
    data["plugins"] = plugins

entries = plugins.get("entries")
if not isinstance(entries, dict):
    entries = {}
    plugins["entries"] = entries

installs = plugins.get("installs")
if not isinstance(installs, dict):
    installs = {}
    plugins["installs"] = installs

load = plugins.get("load")
if not isinstance(load, dict):
    load = {}
    plugins["load"] = load

slots = plugins.get("slots")
if not isinstance(slots, dict):
    slots = {}
    plugins["slots"] = slots

allow = plugins.get("allow")
if not isinstance(allow, list):
    allow = []
    plugins["allow"] = allow

tools = data.get("tools")
if not isinstance(tools, dict):
    tools = {}
    data["tools"] = tools

tool_allow = tools.get("allow")
if not isinstance(tool_allow, list):
    tool_allow = []
    tools["allow"] = tool_allow

tool_also_allow = tools.get("alsoAllow")
if not isinstance(tool_also_allow, list):
    tool_also_allow = []
    tools["alsoAllow"] = tool_also_allow

backup_path = ""
changed = False
delete_candidates: list[str] = []
preserved_sources: list[str] = []
removed_load_paths: list[str] = []

recorded_paths: list[str] = []
install_record = installs.get(plugin_id)
if isinstance(install_record, dict):
    for key in ("installPath", "sourcePath"):
        value = install_record.get(key)
        if isinstance(value, str) and value.strip():
            recorded_paths.append(resolve_text_path(value))

candidate_paths: set[str] = {default_install_dir}
for value in recorded_paths:
    candidate_paths.add(value)
if source_dir_raw:
    candidate_paths.add(resolve_text_path(source_dir_raw))

quoted_key = json.dumps(plugin_id)
if plugin_id in entries:
    entries.pop(plugin_id, None)
    changed = True
if quoted_key in entries:
    entries.pop(quoted_key, None)
    changed = True

if plugin_id in installs:
    installs.pop(plugin_id, None)
    changed = True

if plugin_id in allow:
    plugins["allow"] = [item for item in allow if item != plugin_id]
    allow = plugins["allow"]
    changed = True

memoria_tool_names = {
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
}
kept_tool_allow = [item for item in tool_allow if item not in memoria_tool_names]
if kept_tool_allow != tool_allow:
    tools["allow"] = kept_tool_allow
    tool_allow = kept_tool_allow
    changed = True

kept_tool_also_allow = [item for item in tool_also_allow if item not in memoria_tool_names]
if kept_tool_also_allow != tool_also_allow:
    tools["alsoAllow"] = kept_tool_also_allow
    tool_also_allow = kept_tool_also_allow
    changed = True

agents = data.get("agents")
if isinstance(agents, dict):
    agent_list = agents.get("list")
    if isinstance(agent_list, list):
        for entry in agent_list:
            if not isinstance(entry, dict):
                continue
            agent_tools = entry.get("tools")
            if not isinstance(agent_tools, dict):
                continue

            agent_allow = agent_tools.get("allow")
            if isinstance(agent_allow, list):
                kept_agent_allow = [item for item in agent_allow if item not in memoria_tool_names]
                if kept_agent_allow != agent_allow:
                    agent_tools["allow"] = kept_agent_allow
                    changed = True

            agent_also_allow = agent_tools.get("alsoAllow")
            if isinstance(agent_also_allow, list):
                kept_agent_also_allow = [
                    item for item in agent_also_allow if item not in memoria_tool_names
                ]
                if kept_agent_also_allow != agent_also_allow:
                    agent_tools["alsoAllow"] = kept_agent_also_allow
                    changed = True

            if agent_tools.get("allow") == []:
                agent_tools.pop("allow", None)
            if agent_tools.get("alsoAllow") == []:
                agent_tools.pop("alsoAllow", None)
            if not agent_tools:
                entry.pop("tools", None)

paths = load.get("paths")
if isinstance(paths, list):
    kept_paths: list[object] = []
    for item in paths:
        if not isinstance(item, str):
            kept_paths.append(item)
            continue
        resolved = resolve_text_path(item)
        remove = False
        if resolved in candidate_paths:
            remove = True
        elif plugin_id_for_path(item) == plugin_id:
            remove = True
        elif ("openclaw-memoria" in item or plugin_id in item) and not Path(item).expanduser().exists():
            remove = True
        if remove:
            removed_load_paths.append(item)
            changed = True
        else:
            kept_paths.append(item)
    if kept_paths:
        load["paths"] = kept_paths
    else:
        load.pop("paths", None)

if slots.get("memory") == plugin_id:
    slots["memory"] = "memory-core"
    core_entry = entries.get("memory-core")
    if not isinstance(core_entry, dict):
        core_entry = {}
        entries["memory-core"] = core_entry
    core_entry["enabled"] = True
    changed = True

if not entries:
    plugins.pop("entries", None)
if not installs:
    plugins.pop("installs", None)
if not load:
    plugins.pop("load", None)
if not slots:
    plugins.pop("slots", None)
if not allow:
    plugins.pop("allow", None)
if not plugins:
    data.pop("plugins", None)
if not tool_allow:
    tools.pop("allow", None)
if not tool_also_allow:
    tools.pop("alsoAllow", None)
if not tools:
    data.pop("tools", None)

if changed and config_path.exists():
    backup_path = str(config_path.with_suffix(config_path.suffix + ".bak"))
    Path(backup_path).write_text(config_path.read_text())

if changed:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

requested_delete_paths: list[str] = []
if not keep_source:
    requested_delete_paths.append(default_install_dir)
if source_dir_raw:
    requested_delete_paths.append(resolve_text_path(source_dir_raw))

seen: set[str] = set()
for raw in requested_delete_paths:
    path = resolve_text_path(raw)
    if path in seen:
        continue
    seen.add(path)
    candidate = Path(path)
    if not candidate.exists():
        continue
    if path == default_install_dir or (source_dir_raw and path == resolve_text_path(source_dir_raw)):
        shutil.rmtree(candidate)
        delete_candidates.append(path)
    else:
        preserved_sources.append(path)

result = {
    "ok": True,
    "configFile": str(config_path),
    "configChanged": changed,
    "backup": backup_path,
    "removedLoadPaths": removed_load_paths,
    "deletedPaths": delete_candidates,
    "preservedSources": preserved_sources,
    "slotMemory": slots.get("memory") if isinstance(slots, dict) else None,
}
print(json.dumps(result, ensure_ascii=False))
PY
)" || fail "Uninstall failed"

MANAGED_SKILLS_DIR="$(skills_dir_path)"
for skill_name in memoria-memory memoria-recovery; do
  if [[ -d "${MANAGED_SKILLS_DIR}/${skill_name}" ]]; then
    rm -rf "${MANAGED_SKILLS_DIR:?}/${skill_name}"
    log "Removed managed skill: ${skill_name}"
  fi
done

log "Removed OpenClaw Memoria plugin configuration"
log "${UNINSTALL_RESULT}"

cat <<EOF

Uninstall complete.

Config file: ${CONFIG_FILE}

Recommended follow-up checks:
  cd ~
  openclaw plugins list --json | rg 'memory-memoria|openclaw-memoria' || true
  openclaw config get 'plugins.slots.memory'

If you installed from a custom checkout and still want that directory deleted, rerun with:
  bash scripts/uninstall-openclaw-memoria.sh --source-dir /path/to/openclaw-memoria
EOF
