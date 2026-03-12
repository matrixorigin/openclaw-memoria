"""Shared message format constants for MCP tool responses.

Both the MCP server and contract tests import from here.
Changing a message format requires updating the constant — the contract
test will fail immediately, making the change intentional and visible.
"""

# ── Store ─────────────────────────────────────────────────────────────
MSG_STORED = "Stored memory {memory_id}: {content}"

# ── Retrieve ──────────────────────────────────────────────────────────
MSG_RETRIEVE_FOUND = "Found {count} memories:\n"
MSG_RETRIEVE_EMPTY = "No relevant memories found. Try memory_search with a broader query to see all stored memories."
MSG_RETRIEVE_ITEM = "- [{type}] {content}"
MSG_HEALTH_HEADER = "\n⚠️ Memory health:\n"

# ── Search ────────────────────────────────────────────────────────────
MSG_SEARCH_FOUND = "Found {count} memories:\n"
MSG_SEARCH_EMPTY = "No memories found."
MSG_SEARCH_ITEM = "- [{type}] ({memory_id}) {content}"

# ── Correct ───────────────────────────────────────────────────────────
MSG_CORRECTED_BY_ID = "Corrected → {memory_id}: {content}"
MSG_CORRECTED_BY_QUERY = "Found '{matched}' → corrected to {memory_id}: {content}"
MSG_CORRECT_NO_CONTENT = "new_content is required."
MSG_CORRECT_NO_TARGET = "Provide either memory_id or query."

# ── Purge ─────────────────────────────────────────────────────────────
MSG_PURGED = "Purged {count} memory(ies)."
MSG_PURGE_NO_TARGET = "Provide either memory_id or topic."

# ── Governance ────────────────────────────────────────────────────────
MSG_GOVERNANCE_DONE = "Governance done: "
MSG_GOVERNANCE_SKIPPED = "Governance skipped (cooldown, "
MSG_INDEX_NEEDS_REBUILD = "⚠️  {table}: IVF index needs rebuild"
MSG_INDEX_REBUILT = "✅ {table}: IVF index rebuilt automatically"

# ── Consolidation ─────────────────────────────────────────────────────
MSG_CONSOLIDATION_DONE = "Consolidation done: "
MSG_CONSOLIDATION_SKIPPED = "Consolidation skipped (cooldown, "

# ── Reflection ────────────────────────────────────────────────────────
MSG_REFLECTION_DONE = "Reflection done: scenes_created={scenes_created}, candidates_found={candidates_found}"
MSG_REFLECTION_SKIPPED = "Reflection skipped (cooldown, "
MSG_REFLECTION_NO_CANDIDATES = (
    "No reflection candidates found — not enough cross-session memory patterns yet."
)

# ── Warning suffix ────────────────────────────────────────────────────
MSG_WARNING_PREFIX = "\n⚠️ "
