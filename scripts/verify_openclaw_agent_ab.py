#!/usr/bin/env python3
"""Run an OpenClaw agent A/B verification against the Memoria plugin."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

PLUGIN_ID = "memory-memoria"
REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_PATH = REPO_ROOT / "openclaw" / "bridge.py"


class AgentPreconditionError(RuntimeError):
    """Raised when the local OpenClaw agent cannot start with the current model config."""

    def __init__(self, message: str, code: str = "missing_agent_model") -> None:
        super().__init__(message)
        self.code = code


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _run(cmd: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=env,
    )
    if check and proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(cmd)}: {message}")
    return proc


def _classify_agent_failure(message: str) -> str:
    lowered = message.lower()
    if any(
        marker in lowered
        for marker in (
            "no api key",
            "auth-profiles",
            "provider",
            "model",
            "credential",
            "anthropic",
        )
    ):
        return "missing_agent_model"
    return "agent_command_failed"


def _extract_text_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            part = _extract_text_content(item)
            if part:
                parts.append(part)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return value["text"].strip()
        for key in ("text", "content", "message", "value"):
            if key in value:
                part = _extract_text_content(value[key])
                if part:
                    return part
    return ""


def _extract_assistant_text(payload: Any) -> str:
    if isinstance(payload, dict):
        payloads = payload.get("payloads")
        if isinstance(payloads, list):
            texts = [text for item in payloads if (text := _extract_text_content(item))]
            if texts:
                return texts[-1]

        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict) and message.get("role") == "assistant":
                    text = _extract_text_content(message.get("content"))
                    if text:
                        return text

        for key in ("assistantText", "outputText", "finalText", "replyText", "answer"):
            text = _extract_text_content(payload.get(key))
            if text:
                return text

        for key in ("reply", "result", "response", "data"):
            if key in payload:
                text = _extract_assistant_text(payload[key])
                if text:
                    return text

        for value in payload.values():
            text = _extract_assistant_text(value)
            if text:
                return text

    if isinstance(payload, list):
        for item in reversed(payload):
            text = _extract_assistant_text(item)
            if text:
                return text

    return ""


class BridgeClient:
    def __init__(self, python_executable: str, config: dict[str, Any]) -> None:
        self.python_executable = python_executable
        self.config = config

    def call(self, action: str, params: dict[str, Any]) -> Any:
        request = {"action": action, "config": self.config, "params": params}
        proc = subprocess.run(
            [self.python_executable, str(BRIDGE_PATH)],
            text=True,
            input=json.dumps(request),
            capture_output=True,
            cwd=REPO_ROOT,
        )
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "bridge subprocess failed"
            raise RuntimeError(f"{action}: {message}")

        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"{action}: bridge returned empty stdout")

        payload = json.loads(lines[-1])
        if not payload.get("ok"):
            error = payload.get("error", {})
            raise RuntimeError(f"{action}: {error.get('message', 'unknown error')}")
        return payload["result"]


def _default_python_executable() -> str:
    candidate = REPO_ROOT / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _plugin_config_from_args(args: argparse.Namespace, user_id: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "backend": "embedded",
        "dbUrl": args.db_url,
        "pythonExecutable": args.python_executable,
        "defaultUserId": user_id,
        "userIdStrategy": "config",
        "includeCrossSession": True,
        "autoRecall": True,
        "autoObserve": False,
        "embeddingProvider": args.embedding_provider,
        "embeddingModel": args.embedding_model,
        "embeddingApiKey": args.embedding_api_key,
        "embeddingDim": args.embedding_dim,
    }
    if args.embedding_base_url:
        config["embeddingBaseUrl"] = args.embedding_base_url
    if args.llm_base_url:
        config["llmBaseUrl"] = args.llm_base_url
    if args.llm_api_key:
        config["llmApiKey"] = args.llm_api_key
    if args.llm_model:
        config["llmModel"] = args.llm_model
    return config


def _mutate_isolated_config(
    config_path: Path,
    plugin_config: dict[str, Any],
    workspace_path: Path,
) -> None:
    config = _read_json(config_path)

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
    entry = entries.setdefault(PLUGIN_ID, {})
    if not isinstance(entry, dict):
        entry = {}
        entries[PLUGIN_ID] = entry
    entry["enabled"] = True
    entry["config"] = plugin_config

    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})
    if isinstance(defaults, dict):
        defaults["workspace"] = str(workspace_path)

    hooks = config.setdefault("hooks", {})
    internal = hooks.setdefault("internal", {})
    internal_entries = internal.setdefault("entries", {})
    if not isinstance(internal_entries, dict):
        internal_entries = {}
        internal["entries"] = internal_entries
    session_memory = internal_entries.setdefault("session-memory", {})
    if not isinstance(session_memory, dict):
        session_memory = {}
        internal_entries["session-memory"] = session_memory
    session_memory["enabled"] = False

    _write_json(config_path, config)


def _prepare_isolated_openclaw_home(
    source_config_path: Path,
    source_models_path: Path,
    ) -> tuple[Path, Path]:
    if not source_config_path.exists():
        raise FileNotFoundError(f"OpenClaw config not found: {source_config_path}")

    openclaw_home = Path(tempfile.mkdtemp(prefix="openclaw-memoria-ab-"))
    state_dir = openclaw_home / ".openclaw"
    state_dir.mkdir(parents=True, exist_ok=True)

    source_config = _read_json(source_config_path)
    config: dict[str, Any] = {
        "models": source_config.get("models", {}),
        "agents": source_config.get("agents", {}),
        "hooks": source_config.get("hooks", {}),
        "plugins": {},
    }
    workspace_path = state_dir / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "openclaw.json"
    _write_json(config_path, config)

    if source_models_path.exists():
        target = state_dir / "agents" / "main" / "agent" / "models.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_models_path, target)

    return openclaw_home, config_path


def _contains_token(text: str, token: str) -> bool:
    return token in text


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _run_agent(env: dict[str, str], prompt: str, session_id: str) -> dict[str, Any]:
    cmd = [
        "openclaw",
        "agent",
        "--local",
        "--json",
        "--thinking",
        "off",
        "--timeout",
        "180",
        "--session-id",
        session_id,
        "--message",
        prompt,
    ]
    proc = _run(cmd, env, check=False)
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    if proc.returncode != 0:
        reason = _classify_agent_failure(combined)
        raise AgentPreconditionError(combined.strip() or "agent command failed", code=reason)

    payload = _extract_json_document(combined)
    answer = _extract_assistant_text(payload)
    return {
        "session_id": session_id,
        "answer": answer,
        "raw_json": payload,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plugin-path",
        default=str(REPO_ROOT),
        help="Path to the plugin repo or packed plugin directory.",
    )
    parser.add_argument(
        "--source-openclaw-config",
        default=str(Path.home() / ".openclaw" / "openclaw.json"),
        help="Existing OpenClaw config copied into the isolated home.",
    )
    parser.add_argument(
        "--source-agent-models",
        default=str(Path.home() / ".openclaw" / "agents" / "main" / "agent" / "models.json"),
        help="Existing agent models.json copied into the isolated home when present.",
    )
    parser.add_argument(
        "--db-url",
        default=_env("MEMORIA_DB_URL", "mysql+pymysql://root:111@127.0.0.1:6001/memoria"),
        help="MatrixOne DSN for embedded mode.",
    )
    parser.add_argument(
        "--python-executable",
        default=_env("MEMORIA_PYTHON_EXECUTABLE", _default_python_executable()),
        help="Python executable used by the embedded bridge.",
    )
    parser.add_argument(
        "--embedding-provider",
        default=_env("MEMORIA_EMBEDDING_PROVIDER", "openai"),
        help="Embedding provider passed to Memoria.",
    )
    parser.add_argument(
        "--embedding-model",
        default=_env("MEMORIA_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        help="Embedding model passed to Memoria.",
    )
    parser.add_argument(
        "--embedding-base-url",
        default=_env("MEMORIA_EMBEDDING_BASE_URL"),
        help="Optional OpenAI-compatible embedding base URL.",
    )
    parser.add_argument(
        "--embedding-api-key",
        default=_env("MEMORIA_EMBEDDING_API_KEY"),
        help="Embedding API key.",
    )
    parser.add_argument(
        "--embedding-dim",
        type=int,
        default=int(_env("MEMORIA_EMBEDDING_DIM", "1536")),
        help="Embedding dimension.",
    )
    parser.add_argument(
        "--llm-base-url",
        default=_env("MEMORIA_LLM_BASE_URL"),
        help="Optional OpenAI-compatible LLM base URL for embedded Memoria features.",
    )
    parser.add_argument(
        "--llm-api-key",
        default=_env("MEMORIA_LLM_API_KEY"),
        help="Optional LLM API key for embedded Memoria features.",
    )
    parser.add_argument(
        "--llm-model",
        default=_env("MEMORIA_LLM_MODEL"),
        help="Optional LLM model for embedded Memoria features.",
    )
    args = parser.parse_args()

    if not args.embedding_api_key:
        raise SystemExit("MEMORIA_EMBEDDING_API_KEY or --embedding-api-key is required")

    suffix = uuid.uuid4().hex[:8]
    user_id = f"ab-user-{suffix}"
    rollback_token = f"nebula-rollback-{suffix}"
    session_token = f"delta-window-{suffix}"
    snapshot_name = f"ab-before-delete-{suffix}"
    prompt = "Project Nebula 的回滚口令是什么？如果你不知道，只回复 UNKNOWN。"
    session_prompt = "当前会话的临时暗号是什么？只回答暗号本身。如果不知道，只回复 UNKNOWN。不要输出 session id。"

    plugin_config = _plugin_config_from_args(args, user_id)
    openclaw_home, config_path = _prepare_isolated_openclaw_home(
        Path(args.source_openclaw_config).expanduser().resolve(),
        Path(args.source_agent_models).expanduser().resolve(),
    )

    env = os.environ.copy()
    env["OPENCLAW_HOME"] = str(openclaw_home)

    bridge = BridgeClient(
        args.python_executable,
        {
            "dbUrl": args.db_url,
            "pythonExecutable": args.python_executable,
            "embeddingProvider": args.embedding_provider,
            "embeddingModel": args.embedding_model,
            "embeddingBaseUrl": args.embedding_base_url or None,
            "embeddingApiKey": args.embedding_api_key,
            "embeddingDim": args.embedding_dim,
            "llmBaseUrl": args.llm_base_url or None,
            "llmApiKey": args.llm_api_key or None,
            "llmModel": args.llm_model or None,
        },
    )

    result: dict[str, Any] = {
        "ok": False,
        "openclaw_home": str(openclaw_home),
        "user_id": user_id,
        "rollback_token": rollback_token,
        "snapshot_name": snapshot_name,
        "tool_trace": {},
    }

    try:
        _run(["openclaw", "plugins", "install", "--link", str(Path(args.plugin_path).expanduser().resolve())], env)
        _mutate_isolated_config(config_path, plugin_config, openclaw_home / ".openclaw" / "workspace")
        _run(["openclaw", "plugins", "enable", PLUGIN_ID], env)
        plugins_output = _run(["openclaw", "plugins", "list", "--json"], env)
        plugins_payload = _extract_json_document(
            "\n".join(part for part in (plugins_output.stdout, plugins_output.stderr) if part)
        )
        result["plugin_list"] = plugins_payload
        plugins = plugins_payload.get("plugins") if isinstance(plugins_payload, dict) else plugins_payload
        plugin = (
            next(
                (
                    entry
                    for entry in plugins
                    if isinstance(entry, dict) and entry.get("id") == PLUGIN_ID
                ),
                None,
            )
            if isinstance(plugins, list)
            else None
        )
        _assert(plugin is not None, f"plugin {PLUGIN_ID} missing from plugin list")
        _assert(plugin.get("status") == "loaded", f"plugin {PLUGIN_ID} did not load")

        baseline = _run_agent(env, prompt, f"ab-baseline-{suffix}")
        baseline["contains_token"] = _contains_token(baseline["answer"], rollback_token)
        baseline["pass"] = not baseline["contains_token"]
        result["baseline"] = baseline

        stored = bridge.call(
            "store_memory",
            {
                "user_id": user_id,
                "content": f"Project Nebula 的回滚口令是 {rollback_token}。",
                "memory_type": "semantic",
                "source": "verify_openclaw_agent_ab",
            },
        )
        result["tool_trace"]["store"] = stored
        result["tool_trace"]["search_after_store"] = bridge.call(
            "search_memories",
            {"user_id": user_id, "query": "Project Nebula 回滚口令", "top_k": 5},
        )
        _assert(
            any(
                isinstance(item, dict) and item.get("memory_id") == stored["memory_id"]
                for item in result["tool_trace"]["search_after_store"]
            ),
            "stored memory was not returned by search_memories",
        )
        result["tool_trace"]["snapshot_create"] = bridge.call(
            "snapshot_create",
            {
                "user_id": user_id,
                "name": snapshot_name,
                "description": "verify_openclaw_agent_ab pre-delete snapshot",
            },
        )

        with_memory = _run_agent(env, prompt, f"ab-with-memory-{suffix}")
        with_memory["contains_token"] = _contains_token(with_memory["answer"], rollback_token)
        with_memory["pass"] = with_memory["contains_token"]
        result["with_memory"] = with_memory

        result["tool_trace"]["delete"] = bridge.call(
            "delete_memory",
            {
                "user_id": user_id,
                "memory_id": stored["memory_id"],
                "reason": "verify_openclaw_agent_ab delete",
            },
        )
        result["tool_trace"]["get_after_delete"] = bridge.call(
            "get_memory",
            {"user_id": user_id, "memory_id": stored["memory_id"]},
        )
        _assert(
            result["tool_trace"]["get_after_delete"] is None,
            "deleted memory should not be returned by get_memory",
        )

        after_delete = _run_agent(env, prompt, f"ab-after-delete-{suffix}")
        after_delete["contains_token"] = _contains_token(after_delete["answer"], rollback_token)
        after_delete["pass"] = not after_delete["contains_token"]
        result["after_delete"] = after_delete

        result["tool_trace"]["rollback"] = bridge.call(
            "snapshot_rollback",
            {"user_id": user_id, "name": snapshot_name},
        )
        result["tool_trace"]["get_after_rollback"] = bridge.call(
            "get_memory",
            {"user_id": user_id, "memory_id": stored["memory_id"]},
        )
        _assert(
            result["tool_trace"]["get_after_rollback"] is not None,
            "rolled-back memory should be returned by get_memory",
        )

        after_rollback = _run_agent(env, prompt, f"ab-after-rollback-{suffix}")
        after_rollback["contains_token"] = _contains_token(after_rollback["answer"], rollback_token)
        after_rollback["pass"] = after_rollback["contains_token"]
        result["after_rollback"] = after_rollback

        session_isolation_config = dict(plugin_config)
        session_isolation_config["userIdStrategy"] = "sessionKey"
        session_isolation_config["includeCrossSession"] = False
        session_isolation_config["defaultUserId"] = f"session-default-{suffix}"
        _mutate_isolated_config(config_path, session_isolation_config, openclaw_home / ".openclaw" / "workspace")

        session_a = f"ab-session-a-{suffix}"
        session_b = f"ab-session-b-{suffix}"
        result["tool_trace"]["session_store"] = bridge.call(
            "store_memory",
            {
                "user_id": session_a,
                "session_id": session_a,
                "content": f"当前会话的临时暗号是 {session_token}。这不是 session id。",
                "memory_type": "semantic",
                "source": "verify_openclaw_agent_ab",
            },
        )
        result["tool_trace"]["session_search_a"] = bridge.call(
            "search_memories",
            {
                "user_id": session_a,
                "query": "当前会话 临时 暗号",
                "top_k": 5,
            },
        )
        _assert(
            any(
                isinstance(item, dict)
                and item.get("memory_id") == result["tool_trace"]["session_store"]["memory_id"]
                for item in result["tool_trace"]["session_search_a"]
            ),
            "session-scoped memory was not returned by search_memories for session A",
        )

        session_a_result = _run_agent(env, session_prompt, session_a)
        session_a_result["contains_token"] = _contains_token(session_a_result["answer"], session_token)
        session_a_result["pass"] = session_a_result["contains_token"]

        session_b_result = _run_agent(env, session_prompt, session_b)
        session_b_result["contains_token"] = _contains_token(session_b_result["answer"], session_token)
        session_b_result["pass"] = not session_b_result["contains_token"]

        result["session_isolation"] = {
            "session_a": session_a_result,
            "session_b": session_b_result,
            "pass": session_a_result["pass"] and session_b_result["pass"],
        }

        result["pass"] = all(
            phase.get("pass")
            for phase in (
                result["baseline"],
                result["with_memory"],
                result["after_delete"],
                result["after_rollback"],
                result["session_isolation"],
            )
        )
        result["ok"] = bool(result["pass"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except AgentPreconditionError as exc:
        result["precondition_failed"] = exc.code
        result["message"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:
        result["error"] = exc.__class__.__name__
        result["message"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
