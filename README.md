# Memory (Memoria) for OpenClaw

This package turns `Memoria` into a directly installable OpenClaw `memory` plugin.

The default path is local-first:

- `backend: "embedded"` runs through a bundled Python bridge
- `dbUrl` defaults to a local MatrixOne on `127.0.0.1:6001`
- switching to MatrixOne Cloud is just replacing `dbUrl` with your cloud connection string

It also keeps an optional `backend: "http"` mode for teams that already run the Memoria API.

## 30-second start

If you just want it working, use this path:

- local MatrixOne
- official OpenAI embeddings or another OpenAI-compatible embedding API
- optional OpenAI-compatible LLM API
- `backend: "embedded"`

Minimum values you must know:

- your MatrixOne DSN: `MEMORIA_DB_URL`
- your embedding API key: `MEMORIA_EMBEDDING_API_KEY`
- if you use a non-OpenAI embedding gateway, also set `MEMORIA_EMBEDDING_BASE_URL`
- if you want reflection, entity extraction, or `autoObserve`, also set `MEMORIA_LLM_API_KEY`, `MEMORIA_LLM_MODEL`, and for non-OpenAI gateways `MEMORIA_LLM_BASE_URL`

Quick install:

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_EMBEDDING_DIM='1536' \
    MEMORIA_LLM_BASE_URL='https://api.llm/v1' \
    MEMORIA_LLM_API_KEY='...' \
    MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138' \
    bash -s --
```

Run that as one shell command. Do not put a standalone `\` on its own line.

If `curl | bash` says `command not found: openclaw` but `which openclaw` works in your terminal, rerun with:

```bash
OPENCLAW_BIN="$(which openclaw)" curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    OPENCLAW_BIN="$(which openclaw)" \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_EMBEDDING_DIM='1536' \
    bash -s --
```

This mostly affects macOS users who installed `openclaw` through `pnpm`, because non-interactive shells do not always inherit the same PATH as your interactive terminal.

Quick check:

```bash
cd ~
openclaw memoria capabilities
openclaw memoria stats
openclaw ltm list --limit 10
```

Run the smoke checks outside the plugin repo checkout. If you run `openclaw ...` inside a local `openclaw-memoria` checkout, OpenClaw may auto-load that directory as untracked local code and ignore the installed plugin runtime.

If that works, continue reading only when you need:

- exact field rules: `Fill in your values`
- provider-specific examples: `Copy-paste recipes`
- full validation: `Verification`

## What is packaged

- `openclaw.plugin.json` manifest for OpenClaw discovery and config validation
- `openclaw/index.ts` plugin entry exposing the full embedded Memoria tool surface: search/get/store/retrieve/recall/list/stats/profile/correct/forget, governance, reflect/entity tools, snapshots/rollback, and branches/diff/merge
- `openclaw/bridge.py` embedded bridge for direct MatrixOne access through Memoria
- bundled `memoria/` Python package source so the plugin can run without pointing at another checkout
- `scripts/install-openclaw-memoria.sh` for one-command install into an existing OpenClaw profile
- companion OpenClaw skills under `skills/` for durable memory and rollback recovery behavior
- `scripts/verify_plugin_install.py`, `scripts/verify_capability_coverage.py`, `scripts/verify_embedded_memory.py`, and `scripts/verify_openclaw_agent_ab.py` for repeatable install, coverage, memory, and agent A/B tests

## Compatibility

The plugin keeps Memoria's full embedded capability surface and also adds compatibility entry points for `memory-lancedb-pro` style OpenClaw usage:

- tool alias: `memory_recall` -> `memory_retrieve`
- extra tools: `memory_list`, `memory_stats`
- compatibility CLI: `openclaw ltm list`, `openclaw ltm search`, `openclaw ltm stats`, `openclaw ltm health`

OpenClaw already reserves `openclaw memory` for its built-in file-memory command group, so exact `openclaw memory ...` parity is not possible without a collision. This plugin exposes the compatible CLI surface under `openclaw ltm` instead and reports that mapping via `memory_capabilities`.

## Status

The plugin packaging is ready to test.

What is already covered:

- installable as an OpenClaw `kind: "memory"` plugin
- full embedded Memoria tool surface, including `snapshot`, `rollback`, `branch`, `diff`, and `merge`
- compatibility entry points for `memory-lancedb-pro` style usage: `memory_recall`, `memory_list`, `memory_stats`, and `openclaw ltm ...`
- repeatable verification for plugin install, memory correctness, agent A/B difference, and rollback repair

## Fastest install

The recommended path is:

- local MatrixOne
- remote embedding API
- optional remote LLM API
- `backend: "embedded"`

That gives you the full Memoria feature set without pulling local embedding-model dependencies.

From a repo checkout:

```bash
git clone https://github.com/matrixorigin/openclaw-memoria.git
cd openclaw-memoria
env \
  MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
  MEMORIA_EMBEDDING_PROVIDER='openai' \
  MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
  MEMORIA_EMBEDDING_API_KEY='sk-...' \
  MEMORIA_EMBEDDING_DIM='1536' \
  MEMORIA_LLM_BASE_URL='https://api.llm/v1' \
  MEMORIA_LLM_API_KEY='...' \
  MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138' \
  bash scripts/install-openclaw-memoria.sh --source-dir "$PWD"
```

As a one-liner from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_EMBEDDING_DIM='1536' \
    MEMORIA_LLM_BASE_URL='https://api.llm/v1' \
    MEMORIA_LLM_API_KEY='...' \
    MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138' \
    bash -s --
```

What the installer does:

- uses your explicit checkout when `--source-dir` is provided
- otherwise clones `matrixorigin/openclaw-memoria`
- creates `.venv` and runs `pip install -e .`
- installs and enables `memory-memoria` in OpenClaw
- writes the embedded plugin config into your OpenClaw config file
- adds the full Memoria `memory_*` tool set to global tool policy using `tools.alsoAllow` when possible, or merges them into an existing `tools.allow`
- patches existing `agents.list[].tools` entries the same way so dashboard-managed agents do not stay stuck in read-only memory mode
- enables `plugins.entries["memory-memoria"].hooks.allowPromptInjection` so Memoria-first guidance can reach the system prompt
- installs managed companion skills into `~/.openclaw/skills`: `memoria-memory` and `memoria-recovery`
- repairs stale `plugins.load.paths`, stale `plugins.slots.memory`, and stale `plugins.entries["memory-memoria"]` before install if an older local test left them behind

By default the installer targets remote embedding APIs. Local embeddings remain available as a lower-level option through `--local-embedding`.

## Uninstall

Remove the plugin config and the default managed install directory:

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/uninstall-openclaw-memoria.sh | \
  bash -s --
```

If you installed from a custom checkout and want that directory deleted too:

```bash
bash scripts/uninstall-openclaw-memoria.sh --source-dir /path/to/openclaw-memoria
```

What the uninstall script does:

- removes `plugins.entries["memory-memoria"]`
- removes stale `plugins.entries["\"memory-memoria\""]` from older installers
- removes `plugins.installs["memory-memoria"]`
- removes `memory-memoria` from `plugins.allow`
- removes the Memoria `memory_*` entries that the installer added to global and per-agent tool policy
- removes the managed companion skills `memoria-memory` and `memoria-recovery`
- removes plugin-related `plugins.load.paths`
- restores `plugins.slots.memory` to `memory-core`
- re-enables `memory-core`
- deletes `~/.local/share/openclaw-plugins/openclaw-memoria`

## Troubleshooting

If the assistant says it only has `memory_search` and `memory_get`, that is usually not a Memoria backend failure. It means the agent tool policy only exposed OpenClaw's default `group:memory`, which contains just those two tools. Recent versions of the installer fix this by adding the full Memoria `memory_*` tool set to global tool policy and to existing `agents.list[].tools` entries.

If you installed manually before that fix, reinstall with the installer or add the Memoria tool names to global and agent-level tool policy yourself.

If you create a brand-new agent later in the OpenClaw dashboard and that new agent gets its own explicit tool policy, rerun the installer once or enable the same `memory_*` tools for that agent. OpenClaw does not currently expose an `agents.defaults.tools` config block.

If the assistant keeps saying it will write to `MEMORY.md` or `memory/YYYY-MM-DD.md`, that is OpenClaw's normal workspace-memory behavior. The plugin now injects system guidance telling the agent to prefer Memoria for durable user memory and to treat local memory files as a separate file-based mechanism.

If you want stronger behavior than tool exposure alone, use the bundled managed skills:

- `memoria-memory`: store, recall, correct, and forget durable facts and preferences
- `memoria-recovery`: snapshot and rollback workflows when memory is deleted or corrupted

The installer copies those skills into `~/.openclaw/skills` automatically. The plugin also registers these hooks:

- `before_prompt_build`: injects stable Memoria-first guidance and optional auto-recall context
- `before_agent_start`: legacy compatibility auto-recall path
- `agent_end`: optional auto-observe extraction
- `before_reset`: optional auto-observe before `/new` or `/reset` clears the session
- `after_compaction`: confirms compaction finished so the next turn uses fresh live recall

If embedded mode cannot reach MatrixOne, recent versions return an actionable error instead of only the raw SQL exception. The message now tells the user to either:

- install or start local MatrixOne: `https://github.com/matrixorigin/matrixone`
- or create a MatrixOne cloud instance and replace `dbUrl`: `https://matrixorigin.cn/login`

## AGENTS.md rules

If you want the agent to be more aggressive and consistent about using Memoria, add this to your project `AGENTS.md`:

```markdown
## Memoria rules

- When the user asks to remember, save, update, forget, correct, snapshot, or restore memory, prefer Memoria tools over editing `MEMORY.md` or `memory/YYYY-MM-DD.md`.
- Use `memory_store` or `memory_profile` for durable facts and preferences.
- After storing or correcting something important, verify with `memory_recall` or `memory_search`.
- Before bulk deletion or risky memory cleanup, create a snapshot with `memory_snapshot`.
- If memory was deleted by mistake, inspect `memory_snapshots` and restore with `memory_rollback`.
```

## Fill in your values

Do not guess the config. Fill it using these rules:

- `MEMORIA_DB_URL` is your MatrixOne connection string. Local example: `mysql+pymysql://root:111@127.0.0.1:6001/memoria`
- `MEMORIA_EMBEDDING_PROVIDER` is `openai` for OpenAI-compatible APIs, or `local` for local sentence-transformers
- `MEMORIA_EMBEDDING_MODEL` is the embedding model name your provider expects
- `MEMORIA_EMBEDDING_API_KEY` is required unless `MEMORIA_EMBEDDING_PROVIDER=local`
- `MEMORIA_EMBEDDING_BASE_URL` is required only when your embedding endpoint is not official OpenAI
- `MEMORIA_EMBEDDING_DIM` should always be set in manual config; the installer auto-fills it only for common models such as `text-embedding-3-small`
- `MEMORIA_LLM_API_KEY`, `MEMORIA_LLM_MODEL`, and optionally `MEMORIA_LLM_BASE_URL` are only needed for LLM-backed features such as `memory_extract_entities`, `memory_reflect`, and `autoObserve`
- if your LLM endpoint is official OpenAI, omit `MEMORIA_LLM_BASE_URL`
- if your LLM endpoint is OpenAI-compatible but not OpenAI itself, set `MEMORIA_LLM_BASE_URL`
- for OpenAI SDK compatible providers, the base URL must be the API root

Do not use endpoint URLs as base URLs:

- correct embedding base URL: `https://openrouter.ai/api/v1`
- wrong embedding base URL: `https://openrouter.ai/api/v1/embeddings`
- correct LLM base URL: `https://api.magikcloud.cn/v1`
- wrong LLM base URL: `https://api.magikcloud.cn/v1/chat/completions`

Practical rule:

- official OpenAI embedding: omit `embeddingBaseUrl`
- OpenRouter or other embedding gateway: set `embeddingBaseUrl`
- official OpenAI LLM: omit `llmBaseUrl`
- MagikCloud, Cerebras, vLLM, or other LLM gateway: set `llmBaseUrl`

Common embedding dimensions:

- `text-embedding-3-small` -> `1536`
- `text-embedding-3-large` -> `3072`
- `text-embedding-ada-002` -> `1536`
- `all-MiniLM-L6-v2` -> `384`

If your model is not in that list, set `MEMORIA_EMBEDDING_DIM` yourself.

## Copy-paste recipes

Recommended: local MatrixOne + official OpenAI embeddings + compatible LLM gateway.

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_EMBEDDING_DIM='1536' \
    MEMORIA_LLM_BASE_URL='https://api.llm/v1' \
    MEMORIA_LLM_API_KEY='...' \
    MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138' \
    bash -s --
```

Compatible embedding gateway example. Here `embeddingBaseUrl` is mandatory because the endpoint is not official OpenAI:

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='openai/text-embedding-3-small' \
    MEMORIA_EMBEDDING_BASE_URL='https://openrouter.ai/api/v1' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_EMBEDDING_DIM='1536' \
    bash -s --
```

If you are using OpenRouter specifically, prefer `openai/text-embedding-3-small` over `text-embedding-3-small`.

No LLM example. This is enough for `store/search/retrieve/snapshot/rollback`:

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/openclaw-memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_EMBEDDING_DIM='1536' \
    MEMORIA_AUTO_OBSERVE='false' \
    bash -s --
```

## Manual install

Install the Python runtime once inside this plugin directory.

For local embeddings and the fastest zero-key setup:

```bash
cd /path/to/openclaw-memoria
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[local-embedding]'
```

For OpenAI-compatible embeddings and LLM APIs instead:

```bash
cd /path/to/openclaw-memoria
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then install the plugin into OpenClaw:

```bash
openclaw plugins install --link /path/to/openclaw-memoria
openclaw plugins enable memory-memoria
```

The installer already handles this, but the equivalent config is:

```json
{
  "plugins": {
    "slots": {
      "memory": "memory-memoria"
    }
  }
}
```

## Embedded quick start

Minimal remote-API config:

```json
{
  "plugins": {
    "slots": {
      "memory": "memory-memoria"
    },
    "entries": {
      "memory-memoria": {
        "enabled": true,
        "config": {
          "backend": "embedded",
          "pythonExecutable": "/path/to/openclaw-memoria/.venv/bin/python",
          "defaultUserId": "momo",
          "dbUrl": "mysql+pymysql://root:111@127.0.0.1:6001/memoria",
          "embeddingProvider": "openai",
          "embeddingModel": "text-embedding-3-small",
          "embeddingDim": 1536,
          "embeddingApiKey": "sk-...",
          "llmBaseUrl": "https://api.llm/v1",
          "llmApiKey": "...",
          "llmModel": "ep-deepseek-v3-2-104138",
          "autoRecall": true,
          "autoObserve": false
        }
      }
    }
  }
}
```

The manifest default `dbUrl` already points at local MatrixOne:

```text
mysql+pymysql://root:111@127.0.0.1:6001/memoria
```

To switch to MatrixOne Cloud, keep `backend: "embedded"` and only replace `dbUrl`:

```json
{
  "dbUrl": "mysql+pymysql://<user>:<password>@<cloud-host>:6001/<database>"
}
```

If your local MatrixOne is exposed on a different host port, replace only the port. For example:

```text
mysql+pymysql://root:111@127.0.0.1:6001/memoria
```

Official OpenAI embeddings. `embeddingBaseUrl` is intentionally omitted:

```json
{
  "embeddingProvider": "openai",
  "embeddingModel": "text-embedding-3-small",
  "embeddingApiKey": "${OPENAI_API_KEY}",
  "embeddingDim": 1536
}
```

OpenAI-compatible embedding gateway. `embeddingBaseUrl` is required:

```json
{
  "embeddingProvider": "openai",
  "embeddingModel": "openai/text-embedding-3-small",
  "embeddingBaseUrl": "https://openrouter.ai/api/v1",
  "embeddingApiKey": "${EMBEDDING_API_KEY}",
  "embeddingDim": 1536
}
```

Official OpenAI LLM for reflection/entity extraction. `llmBaseUrl` is intentionally omitted:

```json
{
  "llmApiKey": "${OPENAI_API_KEY}",
  "llmModel": "gpt-4o-mini"
}
```

OpenAI-compatible LLM gateway. `llmBaseUrl` is required:

```json
{
  "llmBaseUrl": "https://api.llm/v1",
  "llmApiKey": "${LLM_API_KEY}",
  "llmModel": "ep-deepseek-v3-2-104138"
}
```

## Local embeddings

Use this only if you explicitly want a zero-key local embedding path:

```json
{
  "backend": "embedded",
  "pythonExecutable": "/path/to/openclaw-memoria/.venv/bin/python",
  "defaultUserId": "momo",
  "embeddingProvider": "local",
  "embeddingModel": "all-MiniLM-L6-v2",
  "autoRecall": true,
  "autoObserve": false
}
```

Install it with:

```bash
bash scripts/install-openclaw-memoria.sh --local-embedding
```

`store/search/retrieve/snapshot/rollback` work without the LLM settings. The `llm*` fields are only needed for LLM-backed features such as `memory_extract_entities`, `memory_reflect`, and `autoObserve`.

## Verification

For a live profile smoke check right after install:

```bash
openclaw memoria capabilities
openclaw memoria stats
openclaw ltm list --limit 10
```

Use an isolated OpenClaw home so install verification does not change your real profile:

```bash
cd /path/to/openclaw-memoria
./.venv/bin/python scripts/verify_plugin_install.py
```

Then verify capability coverage and the compatibility layer:

```bash
cd /path/to/openclaw-memoria
./.venv/bin/python scripts/verify_capability_coverage.py
```

Then verify the embedded memory path. The script covers these checks:

1. memory is stored and retrieved
2. with-memory vs no-memory behavior
3. mistaken delete followed by snapshot rollback repair
4. optional LLM-backed entity extraction

```bash
cd /path/to/openclaw-memoria
export MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria'
export MEMORIA_EMBEDDING_PROVIDER='openai'
export MEMORIA_EMBEDDING_MODEL='openai/text-embedding-3-small'
export MEMORIA_EMBEDDING_BASE_URL='https://openrouter.ai/api/v1'
export MEMORIA_EMBEDDING_API_KEY='...'
export MEMORIA_EMBEDDING_DIM='1536'
export MEMORIA_LLM_BASE_URL='https://api.magikcloud.cn/v1'
export MEMORIA_LLM_API_KEY='...'
export MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138'
./.venv/bin/python scripts/verify_embedded_memory.py
```

If you only want the non-LLM memory checks, omit the `MEMORIA_LLM_*` variables or run:

```bash
./.venv/bin/python scripts/verify_embedded_memory.py --skip-llm
```

Finally, run the real OpenClaw agent A/B verification. This uses your existing `~/.openclaw/openclaw.json` model provider settings, copies them into an isolated `OPENCLAW_HOME`, disables OpenClaw's built-in `session-memory` hook to avoid confounding, and verifies:

1. no seeded memory -> answer does not contain the token
2. seeded memory -> answer contains the token
3. delete memory -> answer stops containing the token
4. rollback snapshot -> answer contains the token again
5. session-scoped memory isolation with `userIdStrategy=sessionKey`

```bash
cd /path/to/openclaw-memoria
export MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6001/memoria'
export MEMORIA_EMBEDDING_PROVIDER='openai'
export MEMORIA_EMBEDDING_MODEL='openai/text-embedding-3-small'
export MEMORIA_EMBEDDING_BASE_URL='https://openrouter.ai/api/v1'
export MEMORIA_EMBEDDING_API_KEY='...'
export MEMORIA_EMBEDDING_DIM='1536'
./.venv/bin/python scripts/verify_openclaw_agent_ab.py
```

Useful manual checks after install:

```bash
openclaw memoria capabilities
openclaw memoria stats
openclaw ltm list --limit 10
openclaw ltm search "rollback token" --limit 5
```

## Optional HTTP mode

If you already run Memoria's HTTP API, use:

```json
{
  "backend": "http",
  "apiUrl": "http://127.0.0.1:8100",
  "apiKey": "${MEMORIA_API_KEY}"
}
```

## Notes

- `userIdStrategy` defaults to `config` because OpenClaw hook contexts do not always expose a stable end-user identity. For single-user quick start this is the least surprising option.
- `memory_search` and `memory_get` are included so the plugin fits OpenClaw's standard memory slot expectations.
- `memory_get` only returns active memories; after `memory_forget`/`memory_purge`, the record disappears from direct lookup until restored by rollback.
- `autoObserve` in embedded mode needs `llmApiKey`/`llmModel` if you want LLM-based extraction. Without those settings, explicit `memory_store` still works.
