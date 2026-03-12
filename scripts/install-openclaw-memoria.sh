#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ID="memory-memoria"
DEFAULT_REPO_URL="https://github.com/matrixorigin/Memoria.git"
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

usage() {
  cat <<'EOF'
Install the OpenClaw Memoria plugin in embedded mode.

Usage:
  bash scripts/install-openclaw-memoria.sh [options]
  curl -fsSL <raw-script-url> | env MEMORIA_EMBEDDING_API_KEY=... bash

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
  OPENCLAW_BIN                    Default: openclaw
  OPENCLAW_HOME                   Optional target OpenClaw home.
  PYTHON_BIN                      Default: python3
  MEMORIA_DB_URL                  Default: mysql+pymysql://root:111@127.0.0.1:6001/memoria
  MEMORIA_DEFAULT_USER_ID         Default: openclaw-user
  MEMORIA_USER_ID_STRATEGY        Default: config
  MEMORIA_AUTO_RECALL             Default: true
  MEMORIA_AUTO_OBSERVE            Default: false
  MEMORIA_EMBEDDING_PROVIDER      Default: openai
  MEMORIA_EMBEDDING_MODEL         Default: text-embedding-3-small
  MEMORIA_EMBEDDING_BASE_URL      Optional OpenAI-compatible base URL
  MEMORIA_EMBEDDING_API_KEY       Required unless provider=local
  MEMORIA_EMBEDDING_DIM           Optional embedding dimensions
  MEMORIA_LLM_BASE_URL            Optional OpenAI-compatible base URL
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

json_string() {
  "$PYTHON_BIN" -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
}

run_openclaw() {
  if [[ -n "${OPENCLAW_HOME_VALUE}" ]]; then
    OPENCLAW_HOME="${OPENCLAW_HOME_VALUE}" "$OPENCLAW_BIN" "$@"
  else
    "$OPENCLAW_BIN" "$@"
  fi
}

config_set_json() {
  local path="$1"
  local value="$2"
  local output
  if ! output="$(run_openclaw config set "$path" "$value" --strict-json 2>&1)"; then
    printf '%s\n' "$output" >&2
    fail "Failed to update ${path}"
  fi
}

config_set_string() {
  config_set_json "$1" "$(json_string "$2")"
}

maybe_config_set_string() {
  local path="$1"
  local value="${2:-}"
  if [[ -n "${value}" ]]; then
    config_set_string "$path" "$value"
  fi
}

maybe_config_set_integer() {
  local path="$1"
  local value="${2:-}"
  if [[ -n "${value}" ]]; then
    case "$value" in
      ''|*[!0-9]*)
        fail "Expected integer for ${path}, got: ${value}"
        ;;
      *)
        config_set_json "$path" "$value"
        ;;
    esac
  fi
}

SOURCE_DIR="${MEMORIA_SOURCE_DIR:-}"
INSTALL_DIR="${MEMORIA_INSTALL_DIR:-$HOME/.local/share/openclaw-plugins/memory-memoria}"
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

need_cmd "$OPENCLAW_BIN"
need_cmd "$PYTHON_BIN"

if [[ -z "${SOURCE_DIR}" ]]; then
  if [[ -f "${PWD}/openclaw.plugin.json" && -f "${PWD}/pyproject.toml" ]]; then
    SOURCE_DIR="${PWD}"
  else
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    REPO_CANDIDATE="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
    if [[ -f "${REPO_CANDIDATE}/openclaw.plugin.json" && -f "${REPO_CANDIDATE}/pyproject.toml" ]]; then
      SOURCE_DIR="${REPO_CANDIDATE}"
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

if [[ "${MEMORIA_EMBEDDING_PROVIDER}" != "local" && -z "${MEMORIA_EMBEDDING_API_KEY}" ]]; then
  fail "MEMORIA_EMBEDDING_API_KEY is required unless provider=local"
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

log "Installing plugin into OpenClaw"
run_openclaw plugins install --link "${SOURCE_DIR}"
run_openclaw plugins enable "${PLUGIN_ID}"

log "Writing plugin configuration"
config_set_string 'plugins.entries["memory-memoria"].config.backend' 'embedded'
config_set_string 'plugins.entries["memory-memoria"].config.pythonExecutable' "${VENV_PYTHON}"
config_set_string 'plugins.entries["memory-memoria"].config.dbUrl' "${MEMORIA_DB_URL}"
config_set_string 'plugins.entries["memory-memoria"].config.defaultUserId' "${MEMORIA_DEFAULT_USER_ID}"
config_set_string 'plugins.entries["memory-memoria"].config.userIdStrategy' "${MEMORIA_USER_ID_STRATEGY}"
config_set_json 'plugins.entries["memory-memoria"].config.autoRecall' "${MEMORIA_AUTO_RECALL}"
config_set_json 'plugins.entries["memory-memoria"].config.autoObserve' "${MEMORIA_AUTO_OBSERVE}"
config_set_string 'plugins.entries["memory-memoria"].config.embeddingProvider' "${MEMORIA_EMBEDDING_PROVIDER}"
config_set_string 'plugins.entries["memory-memoria"].config.embeddingModel' "${MEMORIA_EMBEDDING_MODEL}"
maybe_config_set_string 'plugins.entries["memory-memoria"].config.embeddingBaseUrl' "${MEMORIA_EMBEDDING_BASE_URL}"
maybe_config_set_string 'plugins.entries["memory-memoria"].config.embeddingApiKey' "${MEMORIA_EMBEDDING_API_KEY}"
maybe_config_set_integer 'plugins.entries["memory-memoria"].config.embeddingDim' "${MEMORIA_EMBEDDING_DIM}"
maybe_config_set_string 'plugins.entries["memory-memoria"].config.llmBaseUrl' "${MEMORIA_LLM_BASE_URL}"
maybe_config_set_string 'plugins.entries["memory-memoria"].config.llmApiKey' "${MEMORIA_LLM_API_KEY}"
maybe_config_set_string 'plugins.entries["memory-memoria"].config.llmModel' "${MEMORIA_LLM_MODEL}"

if [[ "${RUN_VERIFY}" == true ]]; then
  log "Running install verification"
  "${VENV_PYTHON}" "${SOURCE_DIR}/scripts/verify_plugin_install.py"
fi

if [[ -n "${OPENCLAW_HOME_VALUE}" ]]; then
  CONFIG_FILE="${OPENCLAW_HOME_VALUE}/.openclaw/openclaw.json"
else
  CONFIG_FILE="$(run_openclaw config file | tail -n 1)"
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
