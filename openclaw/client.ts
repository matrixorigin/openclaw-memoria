import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import type {
  MemoriaMemoryType,
  MemoriaPluginConfig,
  MemoriaTrustTier,
} from "./config.js";
import { MEMORIA_MEMORY_TYPES } from "./config.js";

export type MemoriaMemoryRecord = {
  memory_id: string;
  content: string;
  memory_type?: string;
  trust_tier?: string | null;
  confidence?: number | null;
  session_id?: string | null;
  is_active?: boolean;
  observed_at?: string | null;
  updated_at?: string | null;
};

export type MemoriaProfileResponse = {
  user_id: string;
  profile: string | null;
  stats?: Record<string, unknown>;
};

export type MemoriaReflectCandidate = {
  signal: string;
  importance: number;
  memories: MemoriaMemoryRecord[];
};

export type MemoriaReflectCandidatesResponse = {
  candidates: MemoriaReflectCandidate[];
};

export type MemoriaEntityCandidate = {
  memory_id: string;
  content: string;
};

export type MemoriaEntitySummary = {
  node_id?: string;
  name: string;
  entity_type?: string | null;
  importance?: number | null;
};

export type MemoriaEntityCandidatesResponse = {
  memories: MemoriaEntityCandidate[];
  existing_entities?: Array<{ name: string; entity_type?: string | null }>;
};

export type MemoriaBranchRecord = {
  name: string;
  branch_db?: string;
  active?: boolean;
};

export type MemoriaSnapshotSummary = {
  name: string;
  snapshot_name: string;
  description?: string | null;
  timestamp: string;
};

export type MemoriaListMemoriesResponse = {
  items: MemoriaMemoryRecord[];
  count: number;
  user_id: string;
  backend: string;
  partial?: boolean;
  include_inactive?: boolean;
  limitations?: string[];
};

export type MemoriaStatsResponse = {
  backend: string;
  user_id: string;
  activeMemoryCount: number;
  inactiveMemoryCount: number | null;
  byType: Record<string, number>;
  entityCount: number | null;
  snapshotCount: number | null;
  branchCount: number | null;
  healthWarnings: string[];
  partial?: boolean;
  limitations?: string[];
};

type BridgeEnvelope<T> =
  | { ok: true; result: T }
  | { ok: false; error: { type: string; message: string } };

type MemoriaListPageResponse = {
  items: MemoriaMemoryRecord[];
  next_cursor?: string | null;
};

const BRIDGE_PATH = fileURLToPath(new URL("./bridge.py", import.meta.url));

function normalizeMemoryRecord(value: unknown): MemoriaMemoryRecord {
  const record = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  return {
    memory_id: typeof record.memory_id === "string" ? record.memory_id : "",
    content: typeof record.content === "string" ? record.content : "",
    memory_type:
      typeof record.memory_type === "string"
        ? record.memory_type
        : typeof record.type === "string"
          ? record.type
          : undefined,
    trust_tier:
      typeof record.trust_tier === "string" || record.trust_tier === null
        ? (record.trust_tier as string | null)
        : undefined,
    confidence:
      typeof record.confidence === "number" && Number.isFinite(record.confidence)
        ? record.confidence
        : null,
    session_id:
      typeof record.session_id === "string" || record.session_id === null
        ? (record.session_id as string | null)
        : undefined,
    is_active: typeof record.is_active === "boolean" ? record.is_active : undefined,
    observed_at:
      typeof record.observed_at === "string" || record.observed_at === null
        ? (record.observed_at as string | null)
        : undefined,
    updated_at:
      typeof record.updated_at === "string" || record.updated_at === null
        ? (record.updated_at as string | null)
        : undefined,
  };
}

function normalizeTypeCounts(value: unknown): Record<string, number> {
  const counts = Object.fromEntries(MEMORIA_MEMORY_TYPES.map((type) => [type, 0])) as Record<
    string,
    number
  >;

  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return counts;
  }

  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw === "number" && Number.isFinite(raw)) {
      counts[key] = raw;
      continue;
    }
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const total = (raw as Record<string, unknown>).total;
      if (typeof total === "number" && Number.isFinite(total)) {
        counts[key] = total;
      }
    }
  }

  return counts;
}

function joinUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

function encodeQuery(params: Record<string, string | number | boolean | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) {
      continue;
    }
    query.set(key, String(value));
  }
  const rendered = query.toString();
  return rendered ? `?${rendered}` : "";
}

function tryParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

function extractErrorMessage(payload: unknown): string {
  if (typeof payload === "string" && payload.trim()) {
    return payload.trim();
  }
  if (payload && typeof payload === "object") {
    const detail = (payload as Record<string, unknown>).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
    if (detail && typeof detail === "object") {
      const message = (detail as Record<string, unknown>).message;
      if (typeof message === "string" && message.trim()) {
        return message.trim();
      }
    }
  }
  return "unknown Memoria error";
}

function parseBridgeEnvelope(raw: string): BridgeEnvelope<unknown> {
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const parsed = tryParseJson(lines[index]);
    if (parsed && typeof parsed === "object" && "ok" in parsed) {
      return parsed as BridgeEnvelope<unknown>;
    }
  }

  throw new Error(`Embedded Memoria bridge returned non-JSON output: ${raw.trim() || "<empty>"}`);
}

class MemoriaEmbeddedClient {
  constructor(private readonly config: MemoriaPluginConfig) {}

  private invoke<T>(action: string, params: Record<string, unknown>): Promise<T> {
    return new Promise((resolve, reject) => {
      const child = spawn(this.config.pythonExecutable, [BRIDGE_PATH], {
        cwd: process.cwd(),
        env: { ...process.env },
        stdio: ["pipe", "pipe", "pipe"],
      });

      let stdout = "";
      let stderr = "";
      let settled = false;
      let timedOut = false;

      const timer = setTimeout(() => {
        timedOut = true;
        child.kill("SIGKILL");
      }, this.config.timeoutMs);

      const finish = (fn: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        fn();
      };

      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");

      child.stdout.on("data", (chunk: string) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk: string) => {
        stderr += chunk;
      });
      child.on("error", (error) => {
        finish(() => reject(error));
      });
      child.on("close", (code, signal) => {
        finish(() => {
          if (timedOut) {
            reject(
              new Error(
                `Embedded Memoria bridge timed out after ${this.config.timeoutMs}ms for ${action}.`,
              ),
            );
            return;
          }

          let envelope: BridgeEnvelope<unknown>;
          try {
            envelope = parseBridgeEnvelope(stdout);
          } catch (error) {
            reject(
              new Error(
                `Embedded Memoria bridge failed for ${action} (code=${String(code)} signal=${String(signal)}): ${
                  stderr.trim() || String(error)
                }`,
              ),
            );
            return;
          }

          if (!envelope.ok) {
            reject(new Error(`Embedded Memoria bridge ${action} failed: ${envelope.error.message}`));
            return;
          }

          resolve(envelope.result as T);
        });
      });

      child.stdin.end(
        JSON.stringify({
          action,
          config: {
            backend: this.config.backend,
            dbUrl: this.config.dbUrl,
            pythonExecutable: this.config.pythonExecutable,
            memoriaRoot: this.config.memoriaRoot,
            embeddingProvider: this.config.embeddingProvider,
            embeddingModel: this.config.embeddingModel,
            embeddingBaseUrl: this.config.embeddingBaseUrl,
            embeddingApiKey: this.config.embeddingApiKey,
            embeddingDim: this.config.embeddingDim,
            llmApiKey: this.config.llmApiKey,
            llmBaseUrl: this.config.llmBaseUrl,
            llmModel: this.config.llmModel,
          },
          params,
        }),
      );
    });
  }

  health(userId: string) {
    return this.invoke<{ status: string; mode: string; warnings?: string[] }>("health", {
      user_id: userId,
    });
  }

  storeMemory(params: {
    userId: string;
    content: string;
    memoryType: MemoriaMemoryType;
    trustTier?: MemoriaTrustTier;
    sessionId?: string;
    source?: string;
  }) {
    return this.invoke<MemoriaMemoryRecord>("store_memory", {
      user_id: params.userId,
      content: params.content,
      memory_type: params.memoryType,
      trust_tier: params.trustTier,
      session_id: params.sessionId,
      source: params.source ?? "openclaw_plugin",
    }).then((result) => normalizeMemoryRecord(result));
  }

  retrieve(params: {
    userId: string;
    query: string;
    topK: number;
    sessionId?: string;
    includeCrossSession?: boolean;
  }) {
    return this.invoke<MemoriaMemoryRecord[]>("retrieve_memories", {
      user_id: params.userId,
      query: params.query,
      top_k: params.topK,
      session_id: params.sessionId,
      include_cross_session: params.includeCrossSession ?? true,
    }).then((result) => result.map((entry) => normalizeMemoryRecord(entry)));
  }

  search(params: {
    userId: string;
    query: string;
    topK: number;
  }) {
    return this.invoke<MemoriaMemoryRecord[]>("search_memories", {
      user_id: params.userId,
      query: params.query,
      top_k: params.topK,
    }).then((result) => result.map((entry) => normalizeMemoryRecord(entry)));
  }

  getMemory(params: {
    userId: string;
    memoryId: string;
  }) {
    return this.invoke<MemoriaMemoryRecord | null>("get_memory", {
      user_id: params.userId,
      memory_id: params.memoryId,
    }).then((result) => (result ? normalizeMemoryRecord(result) : null));
  }

  listMemories(params: {
    userId: string;
    memoryType?: MemoriaMemoryType;
    limit: number;
    sessionId?: string;
    includeInactive?: boolean;
  }) {
    return this.invoke<MemoriaListMemoriesResponse>("list_memories", {
      user_id: params.userId,
      memory_type: params.memoryType,
      limit: params.limit,
      session_id: params.sessionId,
      include_inactive: params.includeInactive ?? false,
    }).then((result) => ({
      ...result,
      items: Array.isArray(result.items) ? result.items.map((entry) => normalizeMemoryRecord(entry)) : [],
    }));
  }

  stats(userId: string) {
    return this.invoke<MemoriaStatsResponse>("memory_stats", {
      user_id: userId,
    }).then((result) => ({
      ...result,
      byType: normalizeTypeCounts(result.byType),
    }));
  }

  correctById(params: {
    userId: string;
    memoryId: string;
    newContent: string;
    reason?: string;
  }) {
    return this.invoke<MemoriaMemoryRecord & Record<string, unknown>>("correct_memory", {
      user_id: params.userId,
      memory_id: params.memoryId,
      new_content: params.newContent,
      reason: params.reason ?? "",
    });
  }

  correctByQuery(params: {
    userId: string;
    query: string;
    newContent: string;
    reason?: string;
  }) {
    return this.invoke<MemoriaMemoryRecord & Record<string, unknown>>(
      "correct_memory_by_query",
      {
        user_id: params.userId,
        query: params.query,
        new_content: params.newContent,
        reason: params.reason ?? "",
      },
    );
  }

  deleteMemory(params: {
    userId: string;
    memoryId: string;
    reason?: string;
  }) {
    return this.invoke<{ purged: number }>("delete_memory", {
      user_id: params.userId,
      memory_id: params.memoryId,
      reason: params.reason ?? "",
    });
  }

  purgeMemory(params: {
    userId: string;
    memoryId?: string;
    topic?: string;
    reason?: string;
  }) {
    return this.invoke<{ purged: number } & Record<string, unknown>>("purge_memory", {
      user_id: params.userId,
      memory_id: params.memoryId,
      topic: params.topic,
      reason: params.reason ?? "",
    });
  }

  profile(userId: string) {
    return this.invoke<MemoriaProfileResponse>("profile", {
      user_id: userId,
    });
  }

  governance(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.invoke<Record<string, unknown>>("governance", {
      user_id: params.userId,
      force: params.force ?? false,
    });
  }

  consolidate(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.invoke<Record<string, unknown>>("consolidate", {
      user_id: params.userId,
      force: params.force ?? false,
    });
  }

  reflect(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.invoke<Record<string, unknown>>("reflect", {
      user_id: params.userId,
      force: params.force ?? false,
    });
  }

  extractEntities(userId: string) {
    return this.invoke<Record<string, unknown>>("extract_entities", {
      user_id: userId,
    });
  }

  reflectCandidates(userId: string) {
    return this.invoke<MemoriaReflectCandidatesResponse>("get_reflect_candidates", {
      user_id: userId,
    });
  }

  entityCandidates(userId: string) {
    return this.invoke<MemoriaEntityCandidatesResponse>("get_entity_candidates", {
      user_id: userId,
    });
  }

  linkEntities(params: {
    userId: string;
    entities: Array<Record<string, unknown>>;
  }) {
    return this.invoke<Record<string, unknown>>("link_entities", {
      user_id: params.userId,
      entities: params.entities,
    });
  }

  rebuildIndex(table: string) {
    return this.invoke<{ message: string }>("rebuild_index", {
      user_id: "openclaw-user",
      table,
    });
  }

  listEntities(userId: string) {
    return this.invoke<{ entities: MemoriaEntitySummary[] }>("list_entities", {
      user_id: userId,
    });
  }

  observe(params: {
    userId: string;
    messages: Array<{ role: string; content: string }>;
    sourceEventIds?: string[];
  }) {
    return this.invoke<MemoriaMemoryRecord[]>("observe", {
      user_id: params.userId,
      messages: params.messages,
      source_event_ids: params.sourceEventIds,
    }).then((result) => result.map((entry) => normalizeMemoryRecord(entry)));
  }

  createSnapshot(params: {
    userId: string;
    name: string;
    description?: string;
  }) {
    return this.invoke<MemoriaSnapshotSummary>("snapshot_create", {
      user_id: params.userId,
      name: params.name,
      description: params.description ?? "",
    });
  }

  listSnapshots(userId: string) {
    return this.invoke<MemoriaSnapshotSummary[]>("snapshot_list", {
      user_id: userId,
    });
  }

  rollbackSnapshot(params: {
    userId: string;
    name: string;
  }) {
    return this.invoke<Record<string, unknown>>("snapshot_rollback", {
      user_id: params.userId,
      name: params.name,
    });
  }

  branchCreate(params: {
    userId: string;
    name: string;
    fromSnapshot?: string;
    fromTimestamp?: string;
  }) {
    return this.invoke<Record<string, unknown>>("branch_create", {
      user_id: params.userId,
      name: params.name,
      from_snapshot: params.fromSnapshot,
      from_timestamp: params.fromTimestamp,
    });
  }

  branchList(userId: string) {
    return this.invoke<MemoriaBranchRecord[]>("branch_list", {
      user_id: userId,
    });
  }

  branchCheckout(params: {
    userId: string;
    name: string;
  }) {
    return this.invoke<Record<string, unknown>>("branch_checkout", {
      user_id: params.userId,
      name: params.name,
    });
  }

  branchDelete(params: {
    userId: string;
    name: string;
  }) {
    return this.invoke<Record<string, unknown>>("branch_delete", {
      user_id: params.userId,
      name: params.name,
    });
  }

  branchMerge(params: {
    userId: string;
    source: string;
    strategy: string;
  }) {
    return this.invoke<Record<string, unknown>>("branch_merge", {
      user_id: params.userId,
      source: params.source,
      strategy: params.strategy,
    });
  }

  branchDiff(params: {
    userId: string;
    source: string;
    limit: number;
  }) {
    return this.invoke<Record<string, unknown>>("branch_diff", {
      user_id: params.userId,
      source: params.source,
      limit: params.limit,
    });
  }
}

class MemoriaHttpClient {
  constructor(private readonly config: MemoriaPluginConfig) {}

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    if (!this.config.apiUrl || !this.config.apiKey) {
      throw new Error("apiUrl and apiKey are required when backend=http");
    }

    const response = await fetch(joinUrl(this.config.apiUrl, path), {
      method,
      headers: {
        Authorization: `Bearer ${this.config.apiKey}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeoutMs),
    });

    const raw = await response.text();
    const payload = raw ? tryParseJson(raw) : undefined;

    if (!response.ok) {
      const detail = extractErrorMessage(payload ?? raw);
      throw new Error(`${method} ${path} failed (${response.status}): ${detail}`);
    }

    return (payload ?? raw) as T;
  }

  health(_userId: string) {
    return this.request<{ status: string; database?: string }>("GET", "/health");
  }

  storeMemory(params: {
    content: string;
    memoryType: MemoriaMemoryType;
    trustTier?: MemoriaTrustTier;
    sessionId?: string;
    source?: string;
  }) {
    return this.request<MemoriaMemoryRecord>("POST", "/v1/memories", {
      content: params.content,
      memory_type: params.memoryType,
      trust_tier: params.trustTier,
      session_id: params.sessionId,
      source: params.source ?? "openclaw_plugin",
    }).then((result) => normalizeMemoryRecord(result));
  }

  retrieve(params: {
    query: string;
    topK: number;
    memoryTypes?: MemoriaMemoryType[];
    sessionId?: string;
    includeCrossSession?: boolean;
  }) {
    return this.request<MemoriaMemoryRecord[]>("POST", "/v1/memories/retrieve", {
      query: params.query,
      top_k: params.topK,
      memory_types: params.memoryTypes,
      session_id: params.sessionId,
      include_cross_session: params.includeCrossSession ?? true,
    }).then((result) => result.map((entry) => normalizeMemoryRecord(entry)));
  }

  search(params: {
    query: string;
    topK: number;
  }) {
    return this.request<MemoriaMemoryRecord[]>("POST", "/v1/memories/search", {
      query: params.query,
      top_k: params.topK,
    }).then((result) => result.map((entry) => normalizeMemoryRecord(entry)));
  }

  private async listMemoriesPage(cursor?: string, memoryType?: MemoriaMemoryType) {
    return this.request<MemoriaListPageResponse>(
      "GET",
      `/v1/memories${encodeQuery({ limit: 200, cursor, memory_type: memoryType })}`,
    );
  }

  async getMemory(params: {
    memoryId: string;
  }): Promise<MemoriaMemoryRecord | null> {
    let cursor: string | undefined;
    for (let page = 0; page < this.config.maxListPages; page += 1) {
      const response = await this.listMemoriesPage(cursor);
      const match = response.items.find((item) => item.memory_id === params.memoryId);
      if (match) {
        return normalizeMemoryRecord(match);
      }
      cursor = response.next_cursor ?? undefined;
      if (!cursor) {
        break;
      }
    }
    return null;
  }

  correctById(params: {
    memoryId: string;
    newContent: string;
    reason?: string;
  }) {
    return this.request<MemoriaMemoryRecord>(
      "PUT",
      `/v1/memories/${encodeURIComponent(params.memoryId)}/correct`,
      {
        new_content: params.newContent,
        reason: params.reason ?? "",
      },
    );
  }

  correctByQuery(params: {
    query: string;
    newContent: string;
    reason?: string;
  }) {
    return this.request<MemoriaMemoryRecord & Record<string, unknown>>(
      "POST",
      "/v1/memories/correct",
      {
        query: params.query,
        new_content: params.newContent,
        reason: params.reason ?? "",
      },
    );
  }

  deleteMemory(params: {
    memoryId: string;
    reason?: string;
  }) {
    return this.request<{ purged: number }>(
      "DELETE",
      `/v1/memories/${encodeURIComponent(params.memoryId)}${encodeQuery({
        reason: params.reason ?? "",
      })}`,
    );
  }

  async purgeMemory(params: {
    memoryId?: string;
    topic?: string;
    reason?: string;
  }) {
    if (params.memoryId) {
      return this.deleteMemory({
        memoryId: params.memoryId,
        reason: params.reason,
      });
    }

    const topic = params.topic?.trim();
    if (!topic) {
      throw new Error("memoryId or topic is required");
    }

    const loweredTopic = topic.toLowerCase();
    const ids: string[] = [];
    let cursor: string | undefined;

    for (let page = 0; page < this.config.maxListPages; page += 1) {
      const response = await this.listMemoriesPage(cursor);
      for (const item of response.items) {
        if (item.content.toLowerCase().includes(loweredTopic)) {
          ids.push(item.memory_id);
        }
      }
      cursor = response.next_cursor ?? undefined;
      if (!cursor) {
        break;
      }
    }

    if (ids.length === 0) {
      return { purged: 0 };
    }

    return this.request<{ purged: number }>("POST", "/v1/memories/purge", {
      memory_ids: ids,
      reason: params.reason ?? "",
    });
  }

  async listMemories(params: {
    userId: string;
    memoryType?: MemoriaMemoryType;
    limit: number;
    sessionId?: string;
    includeInactive?: boolean;
  }): Promise<MemoriaListMemoriesResponse> {
    const limitations: string[] = [];
    if (params.includeInactive) {
      limitations.push("HTTP backend cannot list inactive memories.");
    }
    if (params.sessionId) {
      limitations.push("HTTP backend cannot filter memory_list by sessionId.");
    }

    const items: MemoriaMemoryRecord[] = [];
    let cursor: string | undefined;
    for (
      let page = 0;
      page < this.config.maxListPages && items.length < params.limit;
      page += 1
    ) {
      const response = await this.listMemoriesPage(cursor, params.memoryType);
      items.push(...response.items.map((entry) => normalizeMemoryRecord(entry)));
      cursor = response.next_cursor ?? undefined;
      if (!cursor) {
        break;
      }
    }

    return {
      items: items.slice(0, params.limit),
      count: Math.min(items.length, params.limit),
      user_id: params.userId,
      backend: "http",
      partial: limitations.length > 0,
      include_inactive: params.includeInactive ?? false,
      ...(limitations.length > 0 ? { limitations } : {}),
    };
  }

  async stats(userId: string): Promise<MemoriaStatsResponse> {
    const limitations: string[] = [
      "HTTP backend does not expose inactive memory counts.",
      "HTTP backend does not support rollback or branch operations.",
    ];

    let activeMemoryCount = 0;
    let byType = normalizeTypeCounts(undefined);
    let snapshotCount: number | null = null;
    let entityCount: number | null = null;
    let healthWarnings: string[] = [];

    try {
      const profile = await this.profile("me");
      const stats =
        profile.stats && typeof profile.stats === "object" && !Array.isArray(profile.stats)
          ? (profile.stats as Record<string, unknown>)
          : {};
      const total = stats.total;
      activeMemoryCount =
        typeof total === "number" && Number.isFinite(total) ? total : activeMemoryCount;
      byType = normalizeTypeCounts(stats.by_type);
    } catch (error) {
      limitations.push(
        `Profile statistics unavailable: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    try {
      snapshotCount = (await this.listSnapshots()).length;
    } catch (error) {
      limitations.push(
        `Snapshot statistics unavailable: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    try {
      entityCount = (await this.listEntities()).entities.length;
    } catch (error) {
      limitations.push(
        `Entity statistics unavailable: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    try {
      const health = await this.health("me");
      const warnings = (health as Record<string, unknown>).warnings;
      if (Array.isArray(warnings)) {
        healthWarnings = warnings.filter(
          (entry): entry is string => typeof entry === "string" && entry.trim().length > 0,
        );
      }
    } catch (error) {
      limitations.push(
        `Health warnings unavailable: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    return {
      backend: "http",
      user_id: userId,
      activeMemoryCount,
      inactiveMemoryCount: null,
      byType,
      entityCount,
      snapshotCount,
      branchCount: null,
      healthWarnings,
      partial: true,
      limitations,
    };
  }

  profile(userId: string) {
    return this.request<MemoriaProfileResponse>(
      "GET",
      `/v1/profiles/${encodeURIComponent(userId || "me")}`,
    );
  }

  governance(_params: {
    force?: boolean;
  }) {
    throw new Error("Memory governance is only available in embedded mode.");
  }

  consolidate(params: {
    force?: boolean;
  }) {
    return this.request<Record<string, unknown>>(
      "POST",
      `/v1/consolidate${encodeQuery({ force: params.force ?? false })}`,
    );
  }

  reflect(params: {
    force?: boolean;
  }) {
    return this.request<Record<string, unknown>>(
      "POST",
      `/v1/reflect${encodeQuery({ force: params.force ?? false })}`,
    );
  }

  extractEntities(params: {
    force?: boolean;
  }) {
    return this.request<Record<string, unknown>>(
      "POST",
      `/v1/extract-entities${encodeQuery({ force: params.force ?? false })}`,
    );
  }

  reflectCandidates() {
    return this.request<MemoriaReflectCandidatesResponse>("POST", "/v1/reflect/candidates");
  }

  entityCandidates() {
    return this.request<MemoriaEntityCandidatesResponse>(
      "POST",
      "/v1/extract-entities/candidates",
    );
  }

  linkEntities(entities: Array<Record<string, unknown>>) {
    return this.request<Record<string, unknown>>("POST", "/v1/extract-entities/link", {
      entities,
    });
  }

  rebuildIndex(_table: string) {
    throw new Error("Index rebuild is only available in embedded mode.");
  }

  listEntities() {
    return this.request<{ entities: MemoriaEntitySummary[] }>("GET", "/v1/entities");
  }

  observe(params: {
    messages: Array<{ role: string; content: string }>;
    sourceEventIds?: string[];
  }) {
    return this.request<MemoriaMemoryRecord[]>("POST", "/v1/observe", {
      messages: params.messages,
      source_event_ids: params.sourceEventIds,
    }).then((result) => result.map((entry) => normalizeMemoryRecord(entry)));
  }

  createSnapshot(name: string, description = "") {
    return this.request<MemoriaSnapshotSummary>("POST", "/v1/snapshots", {
      name,
      description,
    });
  }

  listSnapshots() {
    return this.request<MemoriaSnapshotSummary[]>("GET", "/v1/snapshots");
  }

  rollbackSnapshot(_params: { name: string }) {
    throw new Error("Snapshot rollback is only available in embedded mode.");
  }

  branchCreate(_params: {
    name: string;
    fromSnapshot?: string;
    fromTimestamp?: string;
  }) {
    throw new Error("Memory branches are only available in embedded mode.");
  }

  branchList() {
    throw new Error("Memory branches are only available in embedded mode.");
  }

  branchCheckout(_params: { name: string }) {
    throw new Error("Memory branches are only available in embedded mode.");
  }

  branchDelete(_params: { name: string }) {
    throw new Error("Memory branches are only available in embedded mode.");
  }

  branchMerge(_params: { source: string; strategy: string }) {
    throw new Error("Memory branches are only available in embedded mode.");
  }

  branchDiff(_params: { source: string; limit: number }) {
    throw new Error("Memory branches are only available in embedded mode.");
  }
}

export class MemoriaClient {
  private readonly embedded?: MemoriaEmbeddedClient;
  private readonly http?: MemoriaHttpClient;

  constructor(private readonly config: MemoriaPluginConfig) {
    if (config.backend === "embedded") {
      this.embedded = new MemoriaEmbeddedClient(config);
    } else {
      this.http = new MemoriaHttpClient(config);
    }
  }

  health(userId: string) {
    return this.embedded ? this.embedded.health(userId) : this.http!.health(userId);
  }

  storeMemory(params: {
    userId: string;
    content: string;
    memoryType: MemoriaMemoryType;
    trustTier?: MemoriaTrustTier;
    sessionId?: string;
    source?: string;
  }) {
    return this.embedded
      ? this.embedded.storeMemory(params)
      : this.http!.storeMemory(params);
  }

  retrieve(params: {
    userId: string;
    query: string;
    topK: number;
    memoryTypes?: MemoriaMemoryType[];
    sessionId?: string;
    includeCrossSession?: boolean;
  }) {
    return this.embedded
      ? this.embedded.retrieve(params)
      : this.http!.retrieve(params);
  }

  search(params: {
    userId: string;
    query: string;
    topK: number;
  }) {
    return this.embedded ? this.embedded.search(params) : this.http!.search(params);
  }

  getMemory(params: {
    userId: string;
    memoryId: string;
  }) {
    return this.embedded
      ? this.embedded.getMemory(params)
      : this.http!.getMemory(params);
  }

  listMemories(params: {
    userId: string;
    memoryType?: MemoriaMemoryType;
    limit: number;
    sessionId?: string;
    includeInactive?: boolean;
  }) {
    return this.embedded
      ? this.embedded.listMemories(params)
      : this.http!.listMemories(params);
  }

  stats(userId: string) {
    return this.embedded ? this.embedded.stats(userId) : this.http!.stats(userId);
  }

  correctById(params: {
    userId: string;
    memoryId: string;
    newContent: string;
    reason?: string;
  }) {
    return this.embedded
      ? this.embedded.correctById(params)
      : this.http!.correctById(params);
  }

  correctByQuery(params: {
    userId: string;
    query: string;
    newContent: string;
    reason?: string;
  }) {
    return this.embedded
      ? this.embedded.correctByQuery(params)
      : this.http!.correctByQuery(params);
  }

  deleteMemory(params: {
    userId: string;
    memoryId: string;
    reason?: string;
  }) {
    return this.embedded
      ? this.embedded.deleteMemory(params)
      : this.http!.deleteMemory(params);
  }

  purgeMemory(params: {
    userId: string;
    memoryId?: string;
    topic?: string;
    reason?: string;
  }) {
    return this.embedded
      ? this.embedded.purgeMemory(params)
      : this.http!.purgeMemory(params);
  }

  profile(userId: string) {
    return this.embedded ? this.embedded.profile(userId) : this.http!.profile(userId);
  }

  governance(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.embedded
      ? this.embedded.governance(params)
      : this.http!.governance(params);
  }

  consolidate(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.embedded
      ? this.embedded.consolidate(params)
      : this.http!.consolidate(params);
  }

  reflect(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.embedded ? this.embedded.reflect(params) : this.http!.reflect(params);
  }

  extractEntities(params: {
    userId: string;
    force?: boolean;
  }) {
    return this.embedded
      ? this.embedded.extractEntities(params.userId)
      : this.http!.extractEntities({ force: params.force });
  }

  reflectCandidates(userId: string) {
    return this.embedded
      ? this.embedded.reflectCandidates(userId)
      : this.http!.reflectCandidates();
  }

  entityCandidates(userId: string) {
    return this.embedded
      ? this.embedded.entityCandidates(userId)
      : this.http!.entityCandidates();
  }

  linkEntities(params: {
    userId: string;
    entities: Array<Record<string, unknown>>;
  }) {
    return this.embedded
      ? this.embedded.linkEntities(params)
      : this.http!.linkEntities(params.entities);
  }

  rebuildIndex(table: string) {
    return this.embedded
      ? this.embedded.rebuildIndex(table)
      : this.http!.rebuildIndex(table);
  }

  listEntities(userId: string) {
    return this.embedded ? this.embedded.listEntities(userId) : this.http!.listEntities();
  }

  observe(params: {
    userId: string;
    messages: Array<{ role: string; content: string }>;
    sourceEventIds?: string[];
  }) {
    return this.embedded ? this.embedded.observe(params) : this.http!.observe(params);
  }

  createSnapshot(params: {
    userId: string;
    name: string;
    description?: string;
  }) {
    return this.embedded
      ? this.embedded.createSnapshot(params)
      : this.http!.createSnapshot(params.name, params.description);
  }

  listSnapshots(userId: string) {
    return this.embedded ? this.embedded.listSnapshots(userId) : this.http!.listSnapshots();
  }

  rollbackSnapshot(params: {
    userId: string;
    name: string;
  }) {
    return this.embedded
      ? this.embedded.rollbackSnapshot(params)
      : this.http!.rollbackSnapshot({ name: params.name });
  }

  branchCreate(params: {
    userId: string;
    name: string;
    fromSnapshot?: string;
    fromTimestamp?: string;
  }) {
    return this.embedded
      ? this.embedded.branchCreate(params)
      : this.http!.branchCreate(params);
  }

  branchList(userId: string) {
    return this.embedded ? this.embedded.branchList(userId) : this.http!.branchList();
  }

  branchCheckout(params: {
    userId: string;
    name: string;
  }) {
    return this.embedded
      ? this.embedded.branchCheckout(params)
      : this.http!.branchCheckout({ name: params.name });
  }

  branchDelete(params: {
    userId: string;
    name: string;
  }) {
    return this.embedded
      ? this.embedded.branchDelete(params)
      : this.http!.branchDelete({ name: params.name });
  }

  branchMerge(params: {
    userId: string;
    source: string;
    strategy: string;
  }) {
    return this.embedded
      ? this.embedded.branchMerge(params)
      : this.http!.branchMerge({
          source: params.source,
          strategy: params.strategy,
        });
  }

  branchDiff(params: {
    userId: string;
    source: string;
    limit: number;
  }) {
    return this.embedded
      ? this.embedded.branchDiff(params)
      : this.http!.branchDiff({
          source: params.source,
          limit: params.limit,
        });
  }
}
