# Brain Agents & Automations Install Guide

This document describes the custom agents and automations that support the brain knowledge graph system.

## Custom Agents

Install these in `~/.copilot/agents/`:

### army-brain-worker.agent.md

**Purpose:** Processes individual data records and adds them to a brain instance using `brain.py`.  
**Model:** claude-haiku-4.5  
**Use case:** Batch ingestion of structured data (spreadsheets, JSON) into the knowledge graph.

```yaml
---
name: army-brain-worker
description: Processes data records into the Army knowledge graph via brain.py add/edge commands.
tools: ["read", "edit", "search", "shell"]
model: claude-haiku-4.5
---
```

**Key behaviors:**
- Reads batch JSON files containing source records
- For each record, calls `brain.py add <type> "<name>" "<content>"` to create the node
- Creates edges to parent/related nodes via `brain.py edge`
- Ignores 429 embedding rate limit errors (node is still created)
- Reports counts on completion

### army-brain-reviewer.agent.md

**Purpose:** Quality assurance — audits the brain for completeness, connectivity, and content accuracy.  
**Model:** claude-sonnet-4.5  
**Use case:** Post-ingestion verification, periodic health checks.

```yaml
---
name: army-brain-reviewer
description: Audits the Army Brain for completeness, correctness, and proper connectivity.
tools: ["read", "search", "shell"]
model: claude-sonnet-4.5
---
```

**Key behaviors:**
- Compares expected node counts vs actual
- Spot-checks random nodes for content completeness
- Verifies hierarchy chains (child → parent edges)
- Reports orphan nodes (zero edges)
- Outputs structured PASS/NEEDS FIXES verdict

---

## Automations

Set these up via Clawpilot's automation system (`m_create_automation`).

### Army Brain Dream (Nightly Consolidation)

**Inspired by:** [garrytan/gbrain](https://github.com/garrytan/gbrain) dream cycle  
**Schedule:** Every day at 2:00 AM  
**Purpose:** Memory consolidation — enriches thin nodes, detects patterns, fixes orphans, re-embeds.

#### Phase Design (adapted from gbrain's 20-phase cycle)

| Phase | gbrain Equivalent | Our Implementation |
|-------|------------------|-------------------|
| 1. Health Check | `stats` | Run `brain.py stats`, report counts |
| 2. Orphan Detection | `orphans` | Sample nodes, check for zero edges |
| 3. Thin Node Enrichment | `enrich_thin` | Find `[No data yet]`/`[Unknown]`, fix from related nodes |
| 4. Pattern Detection | `patterns` | Cross-reference FTS queries, log observations |
| 5. Fact Consolidation | `consolidate` | Detect near-duplicates, flag for review |
| 6. Re-embed | `embed` | Run `brain.py reindex` for stale vectors |
| 7. Report | cycle report | Summarize actions taken |

#### Key Principles (from gbrain)

1. **Significance filter first** — cheap check before expensive LLM work
2. **Conservative changes** — only modify what you're confident about
3. **Idempotent** — safe to re-run; same input = same output
4. **Budget-capped** — limit enrichments per cycle (10 max)
5. **Phase ordering matters** — fix structure before indexing, index before embedding

#### gbrain Patterns We Adapt

| gbrain Pattern | Our Adaptation |
|---------------|----------------|
| Haiku filter → Sonnet synthesis | Check node staleness cheaply, only enrich high-value gaps |
| Fan-out subagents per transcript | Parallel workers per batch file |
| Facts → Takes consolidation | Raw observations → synthesized timeline entries |
| `(file_path, content_hash)` idempotency | Node exists check before re-creating |
| Cooldown guards | Max 1 dream cycle per 24h |
| Allowed slug prefixes | Scope writes to specific node types |

#### Setup Command

```
m_create_automation:
  name: "Army Brain Dream"
  schedule: "every day at 2am"
  prompt: [see full prompt in automation config]
```

### Army Brain Reindex (Embedding Catch-up)

**Schedule:** Every 30 minutes (temporary, auto-disables)  
**Purpose:** Catch up on vector embeddings after bulk data loads when the embedding API rate-limits.

```
m_create_automation:
  name: "Army Brain Reindex"
  schedule: "every 30 minutes"
  prompt: "Run reindex, report embedded vs errors, disable when complete"
```

Pair with a watchdog automation that disables after embeddings reach target count.

---

## Multi-Brain Support

The brain engine supports multiple independent brains via `BRAIN_DIR` environment variable:

```powershell
# Personal brain (default)
$env:BRAIN_DIR="$env:USERPROFILE\.brain"

# Army brain
$env:BRAIN_DIR="$env:USERPROFILE\.army-brain"
```

Each brain has its own:
- `.graph.db` (SQLite with nodes, edges, FTS5, vectors)
- Category folders with markdown files
- Independent embedding state

Agents and automations MUST set `$env:BRAIN_DIR` before every `brain.py` call.

---

## Supervisor Pattern

For large ingestion jobs (1000+ records):

1. **Supervisor** (you or Opus): Splits data into batches, dispatches workers, monitors progress
2. **Workers** (Haiku): Process 50 records each via `brain.py add` + `brain.py edge`
3. **Reviewer** (Sonnet): Audits completed batches for quality
4. **Linker** (Haiku): Creates cross-type edges (subscription→squad, unit→installation)

Workers can run in parallel since they write to different nodes. The SQLite DB handles concurrent writes via WAL mode.
