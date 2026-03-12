# Memory (Memoria) for OpenClaw

This package turns `Memoria` into a directly installable OpenClaw `memory` plugin.

The default path is local-first:

- `backend: "embedded"` runs through a bundled Python bridge
- `dbUrl` defaults to a local MatrixOne on `127.0.0.1:6001`
- switching to MatrixOne Cloud is just replacing `dbUrl` with your cloud connection string

It also keeps an optional `backend: "http"` mode for teams that already run the Memoria API.

## What is packaged

- `openclaw.plugin.json` manifest for OpenClaw discovery and config validation
- `openclaw/index.ts` plugin entry exposing the full embedded Memoria tool surface: search/get/store/retrieve/recall/list/stats/profile/correct/forget, governance, reflect/entity tools, snapshots/rollback, and branches/diff/merge
- `openclaw/bridge.py` embedded bridge for direct MatrixOne access through Memoria
- bundled `memoria/` Python package source so the plugin can run without pointing at another checkout
- `scripts/install-openclaw-memoria.sh` for one-command install into an existing OpenClaw profile
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
cd /path/to/openclaw-memoria
env \
  MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6002/memoria' \
  MEMORIA_EMBEDDING_PROVIDER='openai' \
  MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
  MEMORIA_EMBEDDING_API_KEY='sk-...' \
  MEMORIA_LLM_BASE_URL='https://api.magikcloud.cn/v1' \
  MEMORIA_LLM_API_KEY='...' \
  MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138' \
  bash scripts/install-openclaw-memoria.sh
```

As a one-liner from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/matrixorigin/Memoria/main/scripts/install-openclaw-memoria.sh | \
  env \
    MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6002/memoria' \
    MEMORIA_EMBEDDING_PROVIDER='openai' \
    MEMORIA_EMBEDDING_MODEL='text-embedding-3-small' \
    MEMORIA_EMBEDDING_API_KEY='sk-...' \
    MEMORIA_LLM_BASE_URL='https://api.llm/v1' \
    MEMORIA_LLM_API_KEY='...' \
    MEMORIA_LLM_MODEL='ep-deepseek-v3-2-104138' \
    bash
```

What the installer does:

- clones the repo if you are not already inside a checkout
- creates `.venv` and runs `pip install -e .`
- installs and enables `memory-memoria` in OpenClaw
- writes the embedded plugin config into your OpenClaw config file

By default the installer targets remote embedding APIs. Local embeddings remain available as a lower-level option through `--local-embedding`.

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
          "dbUrl": "mysql+pymysql://root:111@127.0.0.1:6002/memoria",
          "embeddingProvider": "openai",
          "embeddingModel": "text-embedding-3-small",
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
mysql+pymysql://root:111@127.0.0.1:6002/memoria
```

If you prefer official OpenAI embeddings instead of a compatible endpoint, the smallest diff is:

```json
{
  "embeddingProvider": "openai",
  "embeddingModel": "text-embedding-3-small",
  "embeddingBaseUrl": "https://api.openai.com/v1",
  "embeddingApiKey": "${OPENAI_API_KEY}"
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
export MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6002/memoria'
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
export MEMORIA_DB_URL='mysql+pymysql://root:111@127.0.0.1:6002/memoria'
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
