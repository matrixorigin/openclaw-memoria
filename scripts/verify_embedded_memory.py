#!/usr/bin/env python3
"""Run an embedded Memoria smoke test through the OpenClaw bridge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_PATH = REPO_ROOT / "openclaw" / "bridge.py"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class BridgeClient:
    def __init__(self, python_executable: str, config: dict[str, Any]) -> None:
        self.python_executable = python_executable
        self.config = config

    def call(self, action: str, params: dict[str, Any]) -> Any:
        request = {
            "action": action,
            "config": self.config,
            "params": params,
        }
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


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _contains_memory(records: list[dict[str, Any]], memory_id: str) -> bool:
    return any(record.get("memory_id") == memory_id for record in records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db-url",
        default=_env("MEMORIA_DB_URL", "mysql+pymysql://root:111@127.0.0.1:6001/memoria"),
        help="MatrixOne DSN for embedded mode.",
    )
    parser.add_argument(
        "--python-executable",
        default=_env("MEMORIA_PYTHON_EXECUTABLE", sys.executable),
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
        help="Optional OpenAI-compatible LLM base URL.",
    )
    parser.add_argument(
        "--llm-api-key",
        default=_env("MEMORIA_LLM_API_KEY"),
        help="Optional LLM API key for reflection/entity extraction tests.",
    )
    parser.add_argument(
        "--llm-model",
        default=_env("MEMORIA_LLM_MODEL"),
        help="Optional LLM model for reflection/entity extraction tests.",
    )
    parser.add_argument(
        "--user-id",
        default="",
        help="Optional fixed user id. Defaults to a unique smoke-test id.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM-backed entity extraction verification.",
    )
    args = parser.parse_args()

    if not args.embedding_api_key:
        raise SystemExit("MEMORIA_EMBEDDING_API_KEY or --embedding-api-key is required")

    user_id = args.user_id or f"smoke-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    snapshot_name = f"before_delete_{int(time.time())}"
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
        "user_id": user_id,
        "snapshot_name": snapshot_name,
    }

    try:
        query = "nebula rollback 77"
        content = "项目代号 Nebula 的回滚口令是 nebula-rollback-77，主数据库是 MatrixOne，本地端口 6002。"

        result["health"] = bridge.call("health", {"user_id": user_id})
        _assert(result["health"].get("status") == "ok", "embedded health check did not return ok")

        result["search_before"] = bridge.call(
            "search_memories",
            {"user_id": user_id, "query": query, "top_k": 5},
        )
        _assert(result["search_before"] == [], "expected no memories before store")

        result["stored"] = bridge.call(
            "store_memory",
            {
                "user_id": user_id,
                "content": content,
                "memory_type": "semantic",
                "source": "verify_embedded_memory",
            },
        )

        result["search_after_store"] = bridge.call(
            "search_memories",
            {"user_id": user_id, "query": query, "top_k": 5},
        )
        _assert(
            _contains_memory(result["search_after_store"], result["stored"]["memory_id"]),
            "stored memory was not returned by memory_search",
        )

        result["list_after_store"] = bridge.call(
            "list_memories",
            {"user_id": user_id, "limit": 10},
        )
        _assert(
            _contains_memory(result["list_after_store"]["items"], result["stored"]["memory_id"]),
            "stored memory was not returned by memory_list",
        )

        result["stats_after_store"] = bridge.call("memory_stats", {"user_id": user_id})
        _assert(
            result["stats_after_store"].get("activeMemoryCount", 0) >= 1,
            "memory_stats did not report the active stored memory",
        )

        result["snapshot_create"] = bridge.call(
            "snapshot_create",
            {
                "user_id": user_id,
                "name": snapshot_name,
                "description": "verify_embedded_memory pre-delete snapshot",
            },
        )

        result["delete_memory"] = bridge.call(
            "delete_memory",
            {
                "user_id": user_id,
                "memory_id": result["stored"]["memory_id"],
                "reason": "verify_embedded_memory delete",
            },
        )
        result["get_after_delete"] = bridge.call(
            "get_memory",
            {
                "user_id": user_id,
                "memory_id": result["stored"]["memory_id"],
            },
        )
        _assert(result["get_after_delete"] is None, "deleted memory should not be returned by memory_get")

        result["search_after_delete"] = bridge.call(
            "search_memories",
            {"user_id": user_id, "query": query, "top_k": 5},
        )
        _assert(
            not _contains_memory(result["search_after_delete"], result["stored"]["memory_id"]),
            "deleted memory should not be returned by memory_search",
        )

        result["stats_after_delete"] = bridge.call("memory_stats", {"user_id": user_id})
        _assert(
            result["stats_after_delete"].get("inactiveMemoryCount", 0) >= 1,
            "memory_stats did not report the deleted memory as inactive",
        )

        result["rollback"] = bridge.call(
            "snapshot_rollback",
            {"user_id": user_id, "name": snapshot_name},
        )
        result["get_after_rollback"] = bridge.call(
            "get_memory",
            {
                "user_id": user_id,
                "memory_id": result["stored"]["memory_id"],
            },
        )
        _assert(
            result["get_after_rollback"] is not None,
            "rolled-back memory should be returned by memory_get",
        )

        result["search_after_rollback"] = bridge.call(
            "search_memories",
            {"user_id": user_id, "query": query, "top_k": 5},
        )
        _assert(
            _contains_memory(result["search_after_rollback"], result["stored"]["memory_id"]),
            "rolled-back memory was not returned by memory_search",
        )

        result["stats_after_rollback"] = bridge.call("memory_stats", {"user_id": user_id})
        _assert(
            result["stats_after_rollback"].get("activeMemoryCount", 0) >= 1,
            "memory_stats did not report the restored memory as active",
        )

        run_llm_check = not args.skip_llm and bool(args.llm_api_key and args.llm_model)
        if run_llm_check:
            bridge.call(
                "store_memory",
                {
                    "user_id": user_id,
                    "content": "下周我会从上海飞到杭州，在西湖边见客户。",
                    "memory_type": "semantic",
                    "source": "verify_embedded_memory",
                },
            )
            result["extract_entities"] = bridge.call("extract_entities", {"user_id": user_id})
            result["entities"] = bridge.call("list_entities", {"user_id": user_id})
            entity_names = {
                entry.get("name")
                for entry in result["entities"].get("entities", [])
                if isinstance(entry, dict)
            }
            _assert(
                result["extract_entities"].get("entities_found", 0) > 0,
                "LLM entity extraction did not find any entities",
            )
            _assert(
                any(name in entity_names for name in ("上海", "杭州", "西湖")),
                "LLM entity extraction did not create the expected entity nodes",
            )
        else:
            result["extract_entities"] = {"skipped": True}
            result["entities"] = {"skipped": True}

        result["ok"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result["error"] = exc.__class__.__name__
        result["message"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
