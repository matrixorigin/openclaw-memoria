#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ID="memory-memoria"
DEFAULT_REPO_URL="https://github.com/matrixorigin/openclaw-memoria.git"
DEFAULT_REPO_REF="main"

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

resolve_openclaw_bin() {
  local candidate="${1:-openclaw}"
  local resolved=''

  if [[ "${candidate}" == */* ]]; then
    [[ -x "${candidate}" ]] || fail "OPENCLAW_BIN is not executable: ${candidate}"
    printf '%s' "${candidate}"
    return 0
  fi

  resolved="$(command -v "${candidate}" 2>/dev/null || true)"
  if [[ -n "${resolved}" ]]; then
    printf '%s' "${resolved}"
    return 0
  fi

  for fallback in \
    "${HOME}/Library/pnpm/openclaw" \
    "${HOME}/.local/share/pnpm/openclaw" \
    "${HOME}/.pnpm/openclaw"
  do
    if [[ -x "${fallback}" ]]; then
      printf '%s' "${fallback}"
      return 0
    fi
  done

  if command -v pnpm >/dev/null 2>&1; then
    resolved="$(pnpm bin -g 2>/dev/null || true)"
    if [[ -n "${resolved}" && -x "${resolved}/openclaw" ]]; then
      printf '%s' "${resolved}/openclaw"
      return 0
    fi
  fi

  fail "Missing required command: openclaw. Set OPENCLAW_BIN=/absolute/path/to/openclaw"
}

usage() {
  cat <<'EOF'
Install the OpenClaw Memoria plugin in embedded mode.

Usage:
  bash scripts/install-openclaw-memoria.sh [options]
  curl -fsSL <raw-script-url> | env MEMORIA_EMBEDDING_API_KEY=... bash -s --

Options:
  --source-dir <path>   Use an existing checkout instead of cloning.
  --install-dir <path>  Clone target when --source-dir is not provided.
  --repo-url <url>      Git repo to clone when no local checkout is used.
  --ref <ref>           Git branch, tag, or ref to clone. Default: main.
  --local-embedding     Install local embedding extras and set provider=local.
  --skip-pip            Skip pip install; requires an existing .venv.
  --verify              Run verify_plugin_install.py after installation.
  --help                Show this help text.

Environment overrides:
  OPENCLAW_BIN                    Default: auto-detected openclaw executable
  OPENCLAW_HOME                   Optional target OpenClaw home.
  PYTHON_BIN                      Default: python3
  MEMORIA_DB_URL                  Default: mysql+pymysql://root:111@127.0.0.1:6001/memoria
  MEMORIA_DEFAULT_USER_ID         Default: openclaw-user
  MEMORIA_USER_ID_STRATEGY        Default: config
  MEMORIA_AUTO_RECALL             Default: true
  MEMORIA_AUTO_OBSERVE            Default: false
  MEMORIA_EMBEDDING_PROVIDER      Default: openai
  MEMORIA_EMBEDDING_MODEL         Default: text-embedding-3-small
  MEMORIA_EMBEDDING_BASE_URL      Optional for official OpenAI; required for compatible embedding gateways; use the API root, not /embeddings
  MEMORIA_EMBEDDING_API_KEY       Required unless provider=local
  MEMORIA_EMBEDDING_DIM           Auto-filled for common models; otherwise required
  MEMORIA_LLM_BASE_URL            Optional for official OpenAI; required for compatible LLM gateways; use the API root, not /chat/completions
  MEMORIA_LLM_API_KEY             Optional; required if autoObserve=true
  MEMORIA_LLM_MODEL               Optional; required if autoObserve=true
EOF
}

normalize_bool() {
  local raw="${1:-}"
  case "${raw,,}" in
    1|true|yes|on)
      printf 'true'
      ;;
    0|false|no|off)
      printf 'false'
      ;;
    *)
      fail "Expected boolean value, got: ${raw}"
      ;;
  esac
}

infer_embedding_dim() {
  local model="${1:-}"
  case "${model}" in
    text-embedding-3-small|openai/text-embedding-3-small)
      printf '1536'
      ;;
    text-embedding-3-large|openai/text-embedding-3-large)
      printf '3072'
      ;;
    text-embedding-ada-002|openai/text-embedding-ada-002)
      printf '1536'
      ;;
    all-MiniLM-L6-v2|sentence-transformers/all-MiniLM-L6-v2)
      printf '384'
      ;;
    BAAI/bge-m3)
      printf '1024'
      ;;
    *)
      printf ''
      ;;
  esac
}

normalize_base_url() {
  local url="${1:-}"
  url="${url%/}"
  case "${url}" in
    */embeddings)
      url="${url%/embeddings}"
      ;;
    */chat/completions)
      url="${url%/chat/completions}"
      ;;
    */completions)
      url="${url%/completions}"
      ;;
  esac
  printf '%s' "${url}"
}

run_openclaw() {
  if [[ -n "${OPENCLAW_HOME_VALUE}" ]]; then
    OPENCLAW_HOME="${OPENCLAW_HOME_VALUE}" "$OPENCLAW_BIN" "$@"
  else
    "$OPENCLAW_BIN" "$@"
  fi
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

repair_existing_config() {
  local config_file="$1"

  [[ -f "${config_file}" ]] || return 0

  REPAIR_RESULT="$("$PYTHON_BIN" - "${config_file}" "${PLUGIN_ID}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1]).expanduser()
plugin_id = sys.argv[2]

try:
    data = json.loads(config_path.read_text())
except Exception as exc:
    print(f"ERROR\t{exc}")
    raise SystemExit(1)

changed = False
removed_paths: list[str] = []
cleared_slot = False
cleared_entry = False

plugins = data.get("plugins")
if isinstance(plugins, dict):
    load = plugins.get("load")
    if isinstance(load, dict):
        paths = load.get("paths")
        if isinstance(paths, list):
            kept: list[object] = []
            for item in paths:
                if isinstance(item, str):
                    candidate = Path(item).expanduser()
                    if candidate.exists():
                        kept.append(item)
                    else:
                        removed_paths.append(item)
                        changed = True
                else:
                    kept.append(item)
            if kept:
                load["paths"] = kept
            else:
                load.pop("paths", None)
        if not load:
            plugins.pop("load", None)

    entries = plugins.get("entries")
    if isinstance(entries, dict) and plugin_id in entries:
        entries.pop(plugin_id, None)
        cleared_entry = True
        changed = True
        if not entries:
            plugins.pop("entries", None)

    slots = plugins.get("slots")
    if isinstance(slots, dict) and slots.get("memory") == plugin_id:
        slots.pop("memory", None)
        cleared_slot = True
        changed = True
        if not slots:
            plugins.pop("slots", None)

if changed:
    backup_path = config_path.with_suffix(config_path.suffix + ".bak")
    backup_path.write_text(config_path.read_text())
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(
        "CHANGED\t"
        + json.dumps(
            {
                "removedPaths": removed_paths,
                "clearedSlot": cleared_slot,
                "clearedEntry": cleared_entry,
                "backup": str(backup_path),
            },
            ensure_ascii=False,
        )
    )
else:
    print("UNCHANGED\t{}")
PY
)" || fail "Failed to repair existing OpenClaw config: ${config_file}"

  case "${REPAIR_RESULT}" in
    CHANGED$'\t'*)
      log "Repaired stale OpenClaw plugin config in ${config_file}"
      log "${REPAIR_RESULT#*$'\t'}"
      ;;
    UNCHANGED$'\t'*)
      ;;
    *)
      fail "Unexpected config repair result for ${config_file}: ${REPAIR_RESULT}"
      ;;
  esac
}

write_plugin_config() {
  local config_file="$1"

  INSTALLER_CONFIG_FILE="${config_file}" \
  INSTALLER_PLUGIN_ID="${PLUGIN_ID}" \
  INSTALLER_VENV_PYTHON="${VENV_PYTHON}" \
  INSTALLER_MEMORIA_DB_URL="${MEMORIA_DB_URL}" \
  INSTALLER_MEMORIA_DEFAULT_USER_ID="${MEMORIA_DEFAULT_USER_ID}" \
  INSTALLER_MEMORIA_USER_ID_STRATEGY="${MEMORIA_USER_ID_STRATEGY}" \
  INSTALLER_MEMORIA_AUTO_RECALL="${MEMORIA_AUTO_RECALL}" \
  INSTALLER_MEMORIA_AUTO_OBSERVE="${MEMORIA_AUTO_OBSERVE}" \
  INSTALLER_MEMORIA_EMBEDDING_PROVIDER="${MEMORIA_EMBEDDING_PROVIDER}" \
  INSTALLER_MEMORIA_EMBEDDING_MODEL="${MEMORIA_EMBEDDING_MODEL}" \
  INSTALLER_MEMORIA_EMBEDDING_BASE_URL="${MEMORIA_EMBEDDING_BASE_URL}" \
  INSTALLER_MEMORIA_EMBEDDING_API_KEY="${MEMORIA_EMBEDDING_API_KEY}" \
  INSTALLER_MEMORIA_EMBEDDING_DIM="${MEMORIA_EMBEDDING_DIM}" \
  INSTALLER_MEMORIA_LLM_BASE_URL="${MEMORIA_LLM_BASE_URL}" \
  INSTALLER_MEMORIA_LLM_API_KEY="${MEMORIA_LLM_API_KEY}" \
  INSTALLER_MEMORIA_LLM_MODEL="${MEMORIA_LLM_MODEL}" \
  "$PYTHON_BIN" - <<'PY' || fail "Failed to write plugin configuration into ${config_file}"
import json
import os
from pathlib import Path

config_path = Path(os.environ["INSTALLER_CONFIG_FILE"]).expanduser()
plugin_id = os.environ["INSTALLER_PLUGIN_ID"]
memoria_tool_names = [
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


def merge_tool_policy(policy: object) -> dict[str, object]:
    if isinstance(policy, dict):
        result = dict(policy)
    else:
        result = {}

    allow = result.get("allow")
    if isinstance(allow, list):
        for tool_name in memoria_tool_names:
            if tool_name not in allow:
                allow.append(tool_name)
        result["allow"] = allow
        return result

    also_allow = result.get("alsoAllow")
    if isinstance(also_allow, list):
        for tool_name in memoria_tool_names:
            if tool_name not in also_allow:
                also_allow.append(tool_name)
        result["alsoAllow"] = also_allow
        return result

    result["alsoAllow"] = list(memoria_tool_names)
    return result

if config_path.exists():
    data = json.loads(config_path.read_text())
else:
    data = {}

plugins = data.setdefault("plugins", {})
if not isinstance(plugins, dict):
    raise SystemExit("plugins config root is not an object")

allow = plugins.setdefault("allow", [])
if isinstance(allow, list) and plugin_id not in allow:
    allow.append(plugin_id)

entries = plugins.setdefault("entries", {})
if not isinstance(entries, dict):
    raise SystemExit("plugins.entries is not an object")

# Clean up prior buggy installer output that wrote a quoted key name.
entries.pop(json.dumps(plugin_id), None)

plugin_entry = entries.setdefault(plugin_id, {})
if not isinstance(plugin_entry, dict):
    plugin_entry = {}
    entries[plugin_id] = plugin_entry
plugin_entry["enabled"] = True

plugin_config = {
    "backend": "embedded",
    "pythonExecutable": os.environ["INSTALLER_VENV_PYTHON"],
    "dbUrl": os.environ["INSTALLER_MEMORIA_DB_URL"],
    "defaultUserId": os.environ["INSTALLER_MEMORIA_DEFAULT_USER_ID"],
    "userIdStrategy": os.environ["INSTALLER_MEMORIA_USER_ID_STRATEGY"],
    "autoRecall": os.environ["INSTALLER_MEMORIA_AUTO_RECALL"] == "true",
    "autoObserve": os.environ["INSTALLER_MEMORIA_AUTO_OBSERVE"] == "true",
    "embeddingProvider": os.environ["INSTALLER_MEMORIA_EMBEDDING_PROVIDER"],
    "embeddingModel": os.environ["INSTALLER_MEMORIA_EMBEDDING_MODEL"],
}

optional_string_fields = {
    "embeddingBaseUrl": os.environ.get("INSTALLER_MEMORIA_EMBEDDING_BASE_URL", ""),
    "embeddingApiKey": os.environ.get("INSTALLER_MEMORIA_EMBEDDING_API_KEY", ""),
    "llmBaseUrl": os.environ.get("INSTALLER_MEMORIA_LLM_BASE_URL", ""),
    "llmApiKey": os.environ.get("INSTALLER_MEMORIA_LLM_API_KEY", ""),
    "llmModel": os.environ.get("INSTALLER_MEMORIA_LLM_MODEL", ""),
}
for key, value in optional_string_fields.items():
    if value:
        plugin_config[key] = value

embedding_dim = os.environ.get("INSTALLER_MEMORIA_EMBEDDING_DIM", "")
if embedding_dim:
    plugin_config["embeddingDim"] = int(embedding_dim)

plugin_entry["config"] = plugin_config

slots = plugins.setdefault("slots", {})
if not isinstance(slots, dict):
    raise SystemExit("plugins.slots is not an object")
slots["memory"] = plugin_id

tools = data.setdefault("tools", {})
if not isinstance(tools, dict):
    raise SystemExit("tools config root is not an object")

merged_tools = merge_tool_policy(tools)
tools.clear()
tools.update(merged_tools)

agents = data.get("agents")
if isinstance(agents, dict):
    agent_list = agents.get("list")
    if isinstance(agent_list, list):
        for entry in agent_list:
            if not isinstance(entry, dict):
                continue
            merged_agent_tools = merge_tool_policy(entry.get("tools"))
            entry["tools"] = merged_agent_tools

plugin_hooks = plugin_entry.get("hooks")
if not isinstance(plugin_hooks, dict):
    plugin_hooks = {}
    plugin_entry["hooks"] = plugin_hooks
plugin_hooks["allowPromptInjection"] = True

config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY
}

install_bundled_skills() {
  local source_skills_dir="$1"
  local managed_skills_dir="$2"

  [[ -d "${source_skills_dir}" ]] || return 0

  mkdir -p "${managed_skills_dir}"

  local skill_dir=""
  for skill_dir in "${source_skills_dir}"/*; do
    [[ -d "${skill_dir}" ]] || continue
    local skill_name
    skill_name="$(basename -- "${skill_dir}")"
    rm -rf "${managed_skills_dir}/${skill_name}"
    cp -R "${skill_dir}" "${managed_skills_dir}/${skill_name}"
    log "Installed managed skill: ${skill_name}"
  done
}

SOURCE_DIR="${MEMORIA_SOURCE_DIR:-}"
INSTALL_DIR="${MEMORIA_INSTALL_DIR:-$HOME/.local/share/openclaw-plugins/openclaw-memoria}"
REPO_URL="${MEMORIA_REPO_URL:-$DEFAULT_REPO_URL}"
REPO_REF="${MEMORIA_REPO_REF:-$DEFAULT_REPO_REF}"
OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"
OPENCLAW_HOME_VALUE="${OPENCLAW_HOME:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
USE_LOCAL_EMBEDDING=false
SKIP_PIP=false
RUN_VERIFY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-dir)
      SOURCE_DIR="${2:?missing value for --source-dir}"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="${2:?missing value for --install-dir}"
      shift 2
      ;;
    --repo-url)
      REPO_URL="${2:?missing value for --repo-url}"
      shift 2
      ;;
    --ref)
      REPO_REF="${2:?missing value for --ref}"
      shift 2
      ;;
    --local-embedding)
      USE_LOCAL_EMBEDDING=true
      shift
      ;;
    --skip-pip)
      SKIP_PIP=true
      shift
      ;;
    --verify)
      RUN_VERIFY=true
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

OPENCLAW_BIN="$(resolve_openclaw_bin "${OPENCLAW_BIN}")"
need_cmd "$PYTHON_BIN"

if [[ -z "${SOURCE_DIR}" ]]; then
  if [[ -f "${PWD}/openclaw.plugin.json" && -f "${PWD}/pyproject.toml" ]]; then
    SOURCE_DIR="${PWD}"
  else
    SCRIPT_SOURCE="${BASH_SOURCE:-}"
    if [[ -n "${SCRIPT_SOURCE}" ]]; then
      SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_SOURCE}")" && pwd)"
      REPO_CANDIDATE="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
      if [[ -f "${REPO_CANDIDATE}/openclaw.plugin.json" && -f "${REPO_CANDIDATE}/pyproject.toml" ]]; then
        SOURCE_DIR="${REPO_CANDIDATE}"
      fi
    fi
  fi
fi

if [[ -z "${SOURCE_DIR}" ]]; then
  need_cmd git
  SOURCE_DIR="${INSTALL_DIR}"
  mkdir -p "$(dirname -- "${SOURCE_DIR}")"
  if [[ -d "${SOURCE_DIR}/.git" ]]; then
    log "Updating existing checkout in ${SOURCE_DIR}"
    git -C "${SOURCE_DIR}" fetch --depth 1 origin "${REPO_REF}"
    git -C "${SOURCE_DIR}" checkout -f FETCH_HEAD
  elif [[ -e "${SOURCE_DIR}" ]]; then
    fail "Install dir already exists and is not a git checkout: ${SOURCE_DIR}"
  else
    log "Cloning ${REPO_URL}#${REPO_REF} to ${SOURCE_DIR}"
    git clone --depth 1 --branch "${REPO_REF}" "${REPO_URL}" "${SOURCE_DIR}"
  fi
else
  SOURCE_DIR="$(cd -- "${SOURCE_DIR}" && pwd)"
  log "Using existing checkout: ${SOURCE_DIR}"
fi

[[ -f "${SOURCE_DIR}/openclaw.plugin.json" ]] || fail "Missing openclaw.plugin.json in ${SOURCE_DIR}"
[[ -f "${SOURCE_DIR}/pyproject.toml" ]] || fail "Missing pyproject.toml in ${SOURCE_DIR}"

if [[ "${USE_LOCAL_EMBEDDING}" == true ]]; then
  MEMORIA_EMBEDDING_PROVIDER="local"
  MEMORIA_EMBEDDING_MODEL="${MEMORIA_EMBEDDING_MODEL:-all-MiniLM-L6-v2}"
else
  MEMORIA_EMBEDDING_PROVIDER="${MEMORIA_EMBEDDING_PROVIDER:-openai}"
  MEMORIA_EMBEDDING_MODEL="${MEMORIA_EMBEDDING_MODEL:-text-embedding-3-small}"
fi

MEMORIA_DB_URL="${MEMORIA_DB_URL:-mysql+pymysql://root:111@127.0.0.1:6001/memoria}"
MEMORIA_DEFAULT_USER_ID="${MEMORIA_DEFAULT_USER_ID:-openclaw-user}"
MEMORIA_USER_ID_STRATEGY="${MEMORIA_USER_ID_STRATEGY:-config}"
MEMORIA_AUTO_RECALL="$(normalize_bool "${MEMORIA_AUTO_RECALL:-true}")"
MEMORIA_AUTO_OBSERVE="$(normalize_bool "${MEMORIA_AUTO_OBSERVE:-false}")"
MEMORIA_EMBEDDING_BASE_URL="${MEMORIA_EMBEDDING_BASE_URL:-}"
MEMORIA_EMBEDDING_API_KEY="${MEMORIA_EMBEDDING_API_KEY:-}"
MEMORIA_EMBEDDING_DIM="${MEMORIA_EMBEDDING_DIM:-}"
MEMORIA_LLM_BASE_URL="${MEMORIA_LLM_BASE_URL:-}"
MEMORIA_LLM_API_KEY="${MEMORIA_LLM_API_KEY:-}"
MEMORIA_LLM_MODEL="${MEMORIA_LLM_MODEL:-}"
EMBEDDING_BASE_URL_RAW="${MEMORIA_EMBEDDING_BASE_URL}"
LLM_BASE_URL_RAW="${MEMORIA_LLM_BASE_URL}"

MEMORIA_EMBEDDING_BASE_URL="$(normalize_base_url "${MEMORIA_EMBEDDING_BASE_URL}")"
MEMORIA_LLM_BASE_URL="$(normalize_base_url "${MEMORIA_LLM_BASE_URL}")"

if [[ -n "${EMBEDDING_BASE_URL_RAW}" && "${EMBEDDING_BASE_URL_RAW}" != "${MEMORIA_EMBEDDING_BASE_URL}" ]]; then
  log "Normalized embedding base URL to ${MEMORIA_EMBEDDING_BASE_URL}"
fi

if [[ -n "${LLM_BASE_URL_RAW}" && "${LLM_BASE_URL_RAW}" != "${MEMORIA_LLM_BASE_URL}" ]]; then
  log "Normalized LLM base URL to ${MEMORIA_LLM_BASE_URL}"
fi

KNOWN_EMBEDDING_DIM="$(infer_embedding_dim "${MEMORIA_EMBEDDING_MODEL}")"

if [[ "${MEMORIA_EMBEDDING_PROVIDER}" != "local" && -z "${MEMORIA_EMBEDDING_API_KEY}" ]]; then
  fail "MEMORIA_EMBEDDING_API_KEY is required unless provider=local"
fi

if [[ "${MEMORIA_EMBEDDING_PROVIDER}" != "local" && -z "${MEMORIA_EMBEDDING_DIM}" ]]; then
  MEMORIA_EMBEDDING_DIM="${KNOWN_EMBEDDING_DIM}"
  if [[ -z "${MEMORIA_EMBEDDING_DIM}" ]]; then
    fail "MEMORIA_EMBEDDING_DIM is required for model ${MEMORIA_EMBEDDING_MODEL}. Set it explicitly."
  fi
  log "Auto-selected embedding dimension ${MEMORIA_EMBEDDING_DIM} for ${MEMORIA_EMBEDDING_MODEL}"
fi

if [[ "${MEMORIA_EMBEDDING_PROVIDER}" != "local" && -n "${MEMORIA_EMBEDDING_BASE_URL}" && -n "${KNOWN_EMBEDDING_DIM}" && "${MEMORIA_EMBEDDING_DIM}" != "${KNOWN_EMBEDDING_DIM}" ]]; then
  fail "MEMORIA_EMBEDDING_DIM=${MEMORIA_EMBEDDING_DIM} does not match ${MEMORIA_EMBEDDING_MODEL} for a compatible embedding gateway. Use ${KNOWN_EMBEDDING_DIM} and set MEMORIA_EMBEDDING_BASE_URL to the API root."
fi

if [[ "${MEMORIA_AUTO_OBSERVE}" == "true" ]]; then
  [[ -n "${MEMORIA_LLM_API_KEY}" ]] || fail "MEMORIA_AUTO_OBSERVE=true requires MEMORIA_LLM_API_KEY"
  [[ -n "${MEMORIA_LLM_MODEL}" ]] || fail "MEMORIA_AUTO_OBSERVE=true requires MEMORIA_LLM_MODEL"
fi

VENV_DIR="${SOURCE_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

if [[ "${SKIP_PIP}" == true ]]; then
  [[ -x "${VENV_PYTHON}" ]] || fail "--skip-pip requires an existing ${VENV_PYTHON}"
else
  log "Creating/updating virtualenv in ${VENV_DIR}"
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    "$PYTHON_BIN" -m venv "${VENV_DIR}"
  fi
  "${VENV_PYTHON}" -m pip install --upgrade pip setuptools wheel
  if [[ "${USE_LOCAL_EMBEDDING}" == true ]]; then
    "${VENV_PYTHON}" -m pip install -e "${SOURCE_DIR}[local-embedding]"
  else
    "${VENV_PYTHON}" -m pip install -e "${SOURCE_DIR}"
  fi
fi

CONFIG_FILE="$(config_file_path)"
repair_existing_config "${CONFIG_FILE}"

log "Installing plugin into OpenClaw"
run_openclaw plugins install --link "${SOURCE_DIR}"
run_openclaw plugins enable "${PLUGIN_ID}"

log "Writing plugin configuration"
write_plugin_config "${CONFIG_FILE}"
install_bundled_skills "${SOURCE_DIR}/skills" "$(skills_dir_path)"

if [[ "${RUN_VERIFY}" == true ]]; then
  log "Running install verification"
  "${VENV_PYTHON}" "${SOURCE_DIR}/scripts/verify_plugin_install.py"
fi

cat <<EOF

Install complete.

Plugin source: ${SOURCE_DIR}
Python runtime: ${VENV_PYTHON}
OpenClaw config: ${CONFIG_FILE}

Recommended smoke checks:
  openclaw memoria capabilities
  openclaw memoria stats
  openclaw ltm list --limit 10

Full verification scripts:
  ${VENV_PYTHON} ${SOURCE_DIR}/scripts/verify_embedded_memory.py
  ${VENV_PYTHON} ${SOURCE_DIR}/scripts/verify_openclaw_agent_ab.py
EOF
