"""Embedded Memoria bridge for the OpenClaw plugin."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import make_url

ROOT_DIR = Path(__file__).resolve().parent.parent
MEMORIA_MEMORY_TYPES = ("profile", "semantic", "procedural", "working", "tool_result")
MATRIXONE_LOCAL_URL = "https://github.com/matrixorigin/matrixone"
MATRIXONE_CLOUD_URL = "https://matrixorigin.cn/login"


def _fail(message: str) -> None:
    raise ValueError(message)


def _set_env_if_present(env_name: str, value: Any) -> None:
    if value is None:
        return
    text_value = str(value).strip()
    if text_value:
        os.environ[env_name] = text_value


def _format_db_url(db_url: str) -> str:
    try:
        url = make_url(db_url)
    except Exception:
        return db_url or "<empty>"

    host = url.host or "<unknown-host>"
    port = url.port or 6001
    database = url.database or "<unknown-database>"
    return f"{host}:{port}/{database}"


def _matrixone_setup_hint(db_url: str) -> str:
    return "\n".join(
        [
            f"Configured dbUrl: {db_url or '<empty>'}",
            f"Parsed target: {_format_db_url(db_url)}",
            f"If you want local embedded mode, install or start MatrixOne locally: {MATRIXONE_LOCAL_URL}",
            f"If you prefer cloud, create a MatrixOne cloud instance and replace dbUrl with its connection string: {MATRIXONE_CLOUD_URL}",
        ]
    )


def _mysql_error_code(exc: OperationalError) -> int | None:
    original = getattr(exc, "orig", None)
    args = getattr(original, "args", ())
    if not args:
        return None
    code = args[0]
    return code if isinstance(code, int) else None


def _friendly_operational_error(db_url: str, exc: OperationalError) -> str:
    code = _mysql_error_code(exc)
    original = getattr(exc, "orig", None)
    raw_message = str(original or exc)
    target = _format_db_url(db_url)

    if code in {2002, 2003, 2005} or "Connection refused" in raw_message or "Can't connect to MySQL server" in raw_message:
        return (
            "Could not connect to MatrixOne in embedded mode.\n"
            f"Target: {target}\n"
            "This usually means MatrixOne is not running yet, the host/port in dbUrl is wrong, or the instance is not reachable.\n"
            f"{_matrixone_setup_hint(db_url)}"
        )

    if code == 1049 or "Unknown database" in raw_message:
        return (
            "The MatrixOne server is reachable, but the database in dbUrl does not exist yet.\n"
            f"Target: {target}\n"
            "Check the database name in dbUrl, or point the plugin at an existing MatrixOne database.\n"
            f"{_matrixone_setup_hint(db_url)}"
        )

    if code == 1045 or "Access denied" in raw_message:
        return (
            "MatrixOne rejected the username or password from dbUrl.\n"
            f"Target: {target}\n"
            "Check the credentials in dbUrl, or replace it with a valid local or cloud MatrixOne connection string.\n"
            f"{_matrixone_setup_hint(db_url)}"
        )

    return (
        "MatrixOne returned an operational error while initializing Memoria embedded mode.\n"
        f"Target: {target}\n"
        f"Original error: {raw_message}\n"
        f"{_matrixone_setup_hint(db_url)}"
    )


def _resolve_candidate_root(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if path.name == "memoria" and (path / "__init__.py").exists():
        return path.parent
    return path


def _add_memoria_path(config: dict[str, Any]) -> None:
    candidates: list[Path] = []

    configured_root = config.get("memoriaRoot") or config.get("memoria_root")
    env_root = os.environ.get("MEMORIA_ROOT")

    for raw in (configured_root, env_root):
        if isinstance(raw, str) and raw.strip():
            candidates.append(_resolve_candidate_root(raw))

    candidates.append(ROOT_DIR)

    for candidate in candidates:
        if not candidate.exists():
            continue
        if not (candidate / "memoria" / "__init__.py").exists():
            continue
        candidate_text = str(candidate)
        if candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)
        return

    _fail("Unable to locate a Memoria package root for the embedded bridge.")


def _configure_runtime(config: dict[str, Any]) -> None:
    _set_env_if_present("EMBEDDING_PROVIDER", config.get("embeddingProvider"))
    _set_env_if_present("EMBEDDING_MODEL", config.get("embeddingModel"))
    _set_env_if_present("EMBEDDING_BASE_URL", config.get("embeddingBaseUrl"))
    _set_env_if_present("EMBEDDING_API_KEY", config.get("embeddingApiKey"))
    _set_env_if_present("EMBEDDING_DIM", config.get("embeddingDim"))

    _set_env_if_present("MEMORIA_LLM_API_KEY", config.get("llmApiKey"))
    _set_env_if_present("MEMORIA_LLM_BASE_URL", config.get("llmBaseUrl"))
    _set_env_if_present("MEMORIA_LLM_MODEL", config.get("llmModel"))


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _normalize_type_counts(raw: dict[str, Any] | None) -> dict[str, int]:
    counts = {name: 0 for name in MEMORIA_MEMORY_TYPES}
    if not isinstance(raw, dict):
        return counts

    for key, value in raw.items():
        total = value
        if isinstance(value, dict):
            total = value.get("total", 0)
        try:
            counts[str(key)] = int(total or 0)
        except (TypeError, ValueError):
            counts[str(key)] = 0
    return counts


def _memory_to_response(mem: Any) -> dict[str, Any]:
    return {
        "memory_id": mem.memory_id,
        "content": mem.content,
        "memory_type": getattr(mem.memory_type, "value", str(mem.memory_type))
        if getattr(mem, "memory_type", None) is not None
        else None,
        "trust_tier": getattr(mem.trust_tier, "value", str(mem.trust_tier))
        if getattr(mem, "trust_tier", None) is not None
        else None,
        "confidence": getattr(mem, "initial_confidence", None),
        "session_id": getattr(mem, "session_id", None),
        "is_active": bool(getattr(mem, "is_active", True)),
        "observed_at": _isoformat(getattr(mem, "observed_at", None)),
        "updated_at": _isoformat(getattr(mem, "updated_at", None)),
    }


class EmbeddedRuntime:
    def __init__(self, config: dict[str, Any]) -> None:
        _add_memoria_path(config)
        _configure_runtime(config)

        from memoria.api.models import Base as ApiBase
        from memoria.schema import ensure_database, ensure_tables

        db_url = str(config.get("dbUrl", "")).strip()
        if not db_url:
            _fail(
                "dbUrl required for embedded mode.\n"
                "Set a local or cloud MatrixOne connection string first.\n"
                f"If you want local embedded mode, install or start MatrixOne locally: {MATRIXONE_LOCAL_URL}\n"
                f"If you prefer cloud, create a MatrixOne cloud instance and replace dbUrl with its connection string: {MATRIXONE_CLOUD_URL}"
            )

        dim_raw = config.get("embeddingDim")
        dim = 0
        try:
            dim = int(dim_raw) if dim_raw is not None else 0
        except (TypeError, ValueError):
            dim = 0

        engine = create_engine(db_url, pool_pre_ping=True)
        try:
            ensure_database(engine)
            ApiBase.metadata.create_all(bind=engine, checkfirst=True)
            ensure_tables(engine, dim=dim or None)
        finally:
            engine.dispose()

        from memoria.mcp_local.server import EmbeddedBackend

        self._backend = EmbeddedBackend(db_url)

    def _db_factory(self, user_id: str):
        return self._backend._branch_db_factory(user_id)

    def _editor(self, user_id: str):
        return self._backend._create_editor(
            self._db_factory(user_id),
            user_id=user_id,
            embed_client=self._backend._get_embed_client(),
        )

    def _service(self, user_id: str):
        from memoria.core.llm import get_llm_client

        embed_client = self._backend._get_embed_client()
        embed_fn = getattr(embed_client, "embed", None) if embed_client is not None else None
        return self._backend._create_service(
            self._db_factory(user_id),
            user_id=user_id,
            llm_client=get_llm_client(),
            embed_fn=embed_fn,
        )

    def health(self, user_id: str) -> dict[str, Any]:
        warnings = self._backend.health_warnings(user_id)
        with self._db_factory(user_id)() as db:
            db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "mode": "embedded",
            "warnings": warnings,
        }

    def store_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str,
        trust_tier: str | None,
        session_id: str | None,
        source: str,
    ) -> dict[str, Any]:
        from memoria.core.memory.types import MemoryType, TrustTier

        editor = self._editor(user_id)
        memory = editor.inject(
            user_id,
            content,
            memory_type=MemoryType(memory_type),
            trust_tier=TrustTier(trust_tier) if trust_tier else None,
            source=source,
            session_id=session_id,
        )
        return _memory_to_response(memory)

    def retrieve_memories(
        self,
        user_id: str,
        query: str,
        top_k: int,
        session_id: str | None,
        include_cross_session: bool,
    ) -> list[dict[str, Any]]:
        effective_session = None if include_cross_session else session_id
        return self._backend.retrieve(user_id, query, top_k, effective_session)

    def search_memories(self, user_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
        return self._backend.search(user_id, query, top_k)

    def get_memory(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        memory = self._service(user_id).get_memory(memory_id)
        if (
            memory is None
            or getattr(memory, "user_id", user_id) != user_id
            or not bool(getattr(memory, "is_active", True))
        ):
            return None
        return _memory_to_response(memory)

    def list_memories(
        self,
        user_id: str,
        memory_type: str | None,
        limit: int,
        session_id: str | None,
        include_inactive: bool,
    ) -> dict[str, Any]:
        filters = ["user_id = :uid"]
        bind: dict[str, Any] = {
            "uid": user_id,
            "limit": max(1, min(limit, 200)),
        }
        if not include_inactive:
            filters.append("is_active = 1")
        if memory_type:
            filters.append("memory_type = :memory_type")
            bind["memory_type"] = memory_type
        if session_id:
            filters.append("session_id = :session_id")
            bind["session_id"] = session_id

        query = f"""
            SELECT
                memory_id,
                content,
                memory_type,
                trust_tier,
                initial_confidence,
                session_id,
                is_active,
                observed_at,
                updated_at
            FROM mem_memories
            WHERE {" AND ".join(filters)}
            ORDER BY COALESCE(updated_at, observed_at) DESC, observed_at DESC, memory_id DESC
            LIMIT :limit
        """

        with self._db_factory(user_id)() as db:
            rows = db.execute(text(query), bind).fetchall()

        items = [
            {
                "memory_id": row.memory_id,
                "content": row.content,
                "memory_type": row.memory_type,
                "trust_tier": row.trust_tier,
                "confidence": row.initial_confidence,
                "session_id": row.session_id,
                "is_active": bool(row.is_active),
                "observed_at": _isoformat(row.observed_at),
                "updated_at": _isoformat(row.updated_at),
            }
            for row in rows
        ]
        return {
            "items": items,
            "count": len(items),
            "user_id": user_id,
            "backend": "embedded",
            "include_inactive": include_inactive,
        }

    def memory_stats(self, user_id: str) -> dict[str, Any]:
        health_report = self._service(user_id).health_check(user_id)
        warnings = [str(item) for item in self._backend.health_warnings(user_id)]
        pollution = getattr(health_report, "pollution", None)
        if isinstance(pollution, dict) and pollution.get("is_polluted"):
            warnings.append(
                "Recent memory pollution detected; consider reviewing recent writes or rolling back."
            )

        by_type = _normalize_type_counts(getattr(health_report, "per_type_stats", None))
        try:
            entity_count = len(self.list_entities(user_id).get("entities", []))
        except Exception as exc:
            warnings.append(f"Entity count unavailable: {exc}")
            entity_count = 0

        with self._db_factory(user_id)() as db:
            try:
                snapshot_count = db.execute(
                    text(
                        """
                        SELECT COUNT(*) AS count
                        FROM mem_snapshot_registry
                        WHERE user_id = :uid
                        """
                    ),
                    {"uid": user_id},
                ).scalar()
            except Exception as exc:
                warnings.append(f"Snapshot count unavailable: {exc}")
                snapshot_count = 0
            try:
                branch_count = db.execute(
                    text(
                        """
                        SELECT COUNT(*) AS count
                        FROM mem_branches
                        WHERE user_id = :uid AND status = 'active'
                        """
                    ),
                    {"uid": user_id},
                ).scalar()
            except Exception as exc:
                warnings.append(f"Branch count unavailable: {exc}")
                branch_count = 0

        return {
            "backend": "embedded",
            "user_id": user_id,
            "activeMemoryCount": int(getattr(health_report, "active", 0) or 0),
            "inactiveMemoryCount": int(getattr(health_report, "inactive", 0) or 0),
            "byType": by_type,
            "entityCount": int(entity_count or 0),
            "snapshotCount": int(snapshot_count or 0),
            "branchCount": int(branch_count or 0),
            "healthWarnings": warnings,
            "partial": False,
        }

    def correct_memory(
        self,
        user_id: str,
        memory_id: str,
        new_content: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._backend.correct(user_id, memory_id, new_content, reason)

    def correct_memory_by_query(
        self,
        user_id: str,
        query: str,
        new_content: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._backend.correct_by_query(user_id, query, new_content, reason)

    def delete_memory(self, user_id: str, memory_id: str, reason: str) -> dict[str, Any]:
        return self._backend.purge(user_id, memory_id, None, reason)

    def purge_memory(
        self,
        user_id: str,
        memory_id: str | None,
        topic: str | None,
        reason: str,
    ) -> dict[str, Any]:
        return self._backend.purge(user_id, memory_id, topic, reason)

    def profile(self, user_id: str) -> dict[str, Any]:
        return self._backend.profile(user_id)

    def governance(self, user_id: str, force: bool) -> dict[str, Any]:
        return self._backend.governance(user_id, force=force)

    def consolidate(self, user_id: str, force: bool) -> dict[str, Any]:
        return self._backend.consolidate(user_id, force=force)

    def reflect(self, user_id: str, force: bool) -> dict[str, Any]:
        return self._backend.reflect(user_id, force=force)

    def extract_entities(self, user_id: str) -> dict[str, Any]:
        return self._backend.extract_entities(user_id)

    def get_reflect_candidates(self, user_id: str) -> dict[str, Any]:
        return self._backend.get_reflect_candidates(user_id)

    def get_entity_candidates(self, user_id: str) -> dict[str, Any]:
        return self._backend.get_entity_candidates(user_id)

    def link_entities(
        self,
        user_id: str,
        entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._backend.link_entities(user_id, entities)

    def rebuild_index(self, table: str) -> dict[str, Any]:
        return {"message": self._backend.rebuild_index(table)}

    def list_entities(self, user_id: str) -> dict[str, Any]:
        from memoria.core.memory.graph.graph_store import GraphStore
        from memoria.core.memory.graph.types import NodeType

        store = GraphStore(self._db_factory(user_id))
        nodes = store.get_user_nodes(
            user_id,
            node_type=NodeType.ENTITY,
            active_only=True,
            load_embedding=False,
        )
        return {
            "entities": [
                {
                    "node_id": node.node_id,
                    "name": node.content,
                    "entity_type": node.entity_type,
                    "importance": round(node.importance, 2),
                }
                for node in nodes
            ]
        }

    def observe(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
        source_event_ids: list[str] | None,
    ) -> list[dict[str, Any]]:
        memories = self._service(user_id).observe_turn(
            user_id,
            messages,
            source_event_ids=source_event_ids,
        )
        return [_memory_to_response(memory) for memory in memories]

    def snapshot_create(self, user_id: str, name: str, description: str) -> dict[str, Any]:
        return self._backend.snapshot_create(user_id, name, description)

    def snapshot_list(self, user_id: str) -> list[dict[str, Any]]:
        return self._backend.snapshot_list(user_id)

    def snapshot_rollback(self, user_id: str, name: str) -> dict[str, Any]:
        return self._backend.snapshot_rollback(user_id, name)

    def branch_create(
        self,
        user_id: str,
        name: str,
        from_snapshot: str | None,
        from_timestamp: str | None,
    ) -> dict[str, Any]:
        return self._backend.branch_create(
            user_id,
            name,
            from_snapshot,
            from_timestamp,
        )

    def branch_list(self, user_id: str) -> list[dict[str, Any]]:
        return self._backend.branch_list(user_id)

    def branch_checkout(self, user_id: str, name: str) -> dict[str, Any]:
        return self._backend.branch_checkout(user_id, name)

    def branch_delete(self, user_id: str, name: str) -> dict[str, Any]:
        return self._backend.branch_delete(user_id, name)

    def branch_merge(
        self,
        user_id: str,
        source: str,
        strategy: str,
    ) -> dict[str, Any]:
        return self._backend.branch_merge(user_id, source, strategy)

    def branch_diff(
        self,
        user_id: str,
        source: str,
        limit: int,
    ) -> dict[str, Any]:
        return self._backend.branch_diff(user_id, source, limit)


def _dispatch(runtime: EmbeddedRuntime, action: str, params: dict[str, Any]) -> Any:
    if action == "health":
        return runtime.health(str(params.get("user_id", "")).strip() or "openclaw-user")

    user_id = str(params.get("user_id", "")).strip()
    if not user_id:
        _fail("user_id required")

    if action == "store_memory":
        return runtime.store_memory(
            user_id=user_id,
            content=str(params.get("content", "")).strip(),
            memory_type=str(params.get("memory_type", "semantic")).strip() or "semantic",
            trust_tier=(
                str(params.get("trust_tier", "")).strip() or None
                if params.get("trust_tier") is not None
                else None
            ),
            session_id=(
                str(params.get("session_id", "")).strip() or None
                if params.get("session_id") is not None
                else None
            ),
            source=str(params.get("source", "openclaw_plugin")).strip() or "openclaw_plugin",
        )

    if action == "retrieve_memories":
        return runtime.retrieve_memories(
            user_id=user_id,
            query=str(params.get("query", "")).strip(),
            top_k=int(params.get("top_k", 5)),
            session_id=(
                str(params.get("session_id", "")).strip() or None
                if params.get("session_id") is not None
                else None
            ),
            include_cross_session=bool(params.get("include_cross_session", True)),
        )

    if action == "search_memories":
        return runtime.search_memories(
            user_id=user_id,
            query=str(params.get("query", "")).strip(),
            top_k=int(params.get("top_k", 5)),
        )

    if action == "get_memory":
        return runtime.get_memory(
            user_id=user_id,
            memory_id=str(params.get("memory_id", "")).strip(),
        )

    if action == "list_memories":
        return runtime.list_memories(
            user_id=user_id,
            memory_type=(
                str(params.get("memory_type", "")).strip() or None
                if params.get("memory_type") is not None
                else None
            ),
            limit=int(params.get("limit", 20)),
            session_id=(
                str(params.get("session_id", "")).strip() or None
                if params.get("session_id") is not None
                else None
            ),
            include_inactive=bool(params.get("include_inactive", False)),
        )

    if action == "memory_stats":
        return runtime.memory_stats(user_id)

    if action == "correct_memory":
        return runtime.correct_memory(
            user_id=user_id,
            memory_id=str(params.get("memory_id", "")).strip(),
            new_content=str(params.get("new_content", "")).strip(),
            reason=str(params.get("reason", "")).strip(),
        )

    if action == "correct_memory_by_query":
        return runtime.correct_memory_by_query(
            user_id=user_id,
            query=str(params.get("query", "")).strip(),
            new_content=str(params.get("new_content", "")).strip(),
            reason=str(params.get("reason", "")).strip(),
        )

    if action == "delete_memory":
        return runtime.delete_memory(
            user_id=user_id,
            memory_id=str(params.get("memory_id", "")).strip(),
            reason=str(params.get("reason", "")).strip(),
        )

    if action == "purge_memory":
        return runtime.purge_memory(
            user_id=user_id,
            memory_id=(
                str(params.get("memory_id", "")).strip() or None
                if params.get("memory_id") is not None
                else None
            ),
            topic=(
                str(params.get("topic", "")).strip() or None
                if params.get("topic") is not None
                else None
            ),
            reason=str(params.get("reason", "")).strip(),
        )

    if action == "profile":
        return runtime.profile(user_id)

    if action == "governance":
        return runtime.governance(
            user_id=user_id,
            force=bool(params.get("force", False)),
        )

    if action == "consolidate":
        return runtime.consolidate(
            user_id=user_id,
            force=bool(params.get("force", False)),
        )

    if action == "reflect":
        return runtime.reflect(
            user_id=user_id,
            force=bool(params.get("force", False)),
        )

    if action == "extract_entities":
        return runtime.extract_entities(user_id)

    if action == "get_reflect_candidates":
        return runtime.get_reflect_candidates(user_id)

    if action == "get_entity_candidates":
        return runtime.get_entity_candidates(user_id)

    if action == "link_entities":
        entities = params.get("entities")
        if not isinstance(entities, list):
            _fail("entities must be an array")
        normalized_entities = [item for item in entities if isinstance(item, dict)]
        return runtime.link_entities(
            user_id=user_id,
            entities=normalized_entities,
        )

    if action == "rebuild_index":
        return runtime.rebuild_index(
            str(params.get("table", "mem_memories")).strip() or "mem_memories",
        )

    if action == "list_entities":
        return runtime.list_entities(user_id)

    if action == "observe":
        messages = params.get("messages")
        if not isinstance(messages, list):
            _fail("messages must be an array")
        source_event_ids = params.get("source_event_ids")
        if source_event_ids is not None and not isinstance(source_event_ids, list):
            _fail("source_event_ids must be an array")
        return runtime.observe(
            user_id=user_id,
            messages=messages,
            source_event_ids=source_event_ids,
        )

    if action == "snapshot_create":
        return runtime.snapshot_create(
            user_id=user_id,
            name=str(params.get("name", "")).strip(),
            description=str(params.get("description", "")).strip(),
        )

    if action == "snapshot_list":
        return runtime.snapshot_list(user_id)

    if action == "snapshot_rollback":
        return runtime.snapshot_rollback(
            user_id=user_id,
            name=str(params.get("name", "")).strip(),
        )

    if action == "branch_create":
        return runtime.branch_create(
            user_id=user_id,
            name=str(params.get("name", "")).strip(),
            from_snapshot=(
                str(params.get("from_snapshot", "")).strip() or None
                if params.get("from_snapshot") is not None
                else None
            ),
            from_timestamp=(
                str(params.get("from_timestamp", "")).strip() or None
                if params.get("from_timestamp") is not None
                else None
            ),
        )

    if action == "branch_list":
        return runtime.branch_list(user_id)

    if action == "branch_checkout":
        return runtime.branch_checkout(
            user_id=user_id,
            name=str(params.get("name", "")).strip(),
        )

    if action == "branch_delete":
        return runtime.branch_delete(
            user_id=user_id,
            name=str(params.get("name", "")).strip(),
        )

    if action == "branch_merge":
        return runtime.branch_merge(
            user_id=user_id,
            source=str(params.get("source", "")).strip(),
            strategy=str(params.get("strategy", "append")).strip() or "append",
        )

    if action == "branch_diff":
        return runtime.branch_diff(
            user_id=user_id,
            source=str(params.get("source", "")).strip(),
            limit=int(params.get("limit", 50)),
        )

    _fail(f"Unsupported action: {action}")


def main() -> int:
    config: dict[str, Any] = {}
    try:
        request = json.loads(sys.stdin.read() or "{}")
        config = request.get("config") if isinstance(request.get("config"), dict) else {}
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        action = str(request.get("action", "")).strip()
        if not action:
            _fail("Missing bridge action")

        runtime = EmbeddedRuntime(config)
        result = _dispatch(runtime, action, params)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except OperationalError as exc:  # pragma: no cover - subprocess boundary
        db_url = str(config.get("dbUrl", "")).strip()
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": exc.__class__.__name__,
                        "message": _friendly_operational_error(db_url, exc),
                    },
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:  # pragma: no cover - subprocess boundary
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
