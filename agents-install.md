# Brain Agents & Automations Install Guide

This document describes optional custom agents and automations for maintaining a
generic Brain knowledge graph. The default brain lives in `~/.brain/`; use
`--brain <path>` or `BRAIN_DIR` for any other vault.

## Agent Installation

Install agent definitions in `~/.copilot/agents/` as `.agent.md` files. Keep
frontmatter minimal and place durable behavior rules in the agent body or the
target vault's `AGENTS.md`.

Install checklist:

1. Create one `.agent.md` file per recommended agent below.
2. Copy the YAML frontmatter and behavior contract into that file.
3. Replace the brain path only if the agent should target a non-default vault.
4. Run `python <skill-dir>\brain.py stats` to confirm the target brain opens.
5. Run `python <skill-dir>\brain.py audit-enrichment --limit=5` to confirm the
   maintenance command returns JSON candidates.

Each agent should set the brain path explicitly before invoking the engine:

```powershell
$env:BRAIN_DIR = "$env:USERPROFILE\.brain"
$brainPy = "$env:USERPROFILE\.copilot\m-skills\brain\brain.py"
python $brainPy stats
```

For a separate vault:

```powershell
python $brainPy --brain "$env:USERPROFILE\.brain-customer-a" stats
```

## Recommended Agents

### brain-ingest-worker.agent.md

**Purpose:** Process a bounded batch of source records into Brain markdown pages
and graph edges.

**Model:** `claude-haiku-4.5`

**Use case:** Batch ingestion from spreadsheets, JSON exports, meeting notes, or
curated source snippets.

```yaml
---
name: brain-ingest-worker
description: Processes bounded source-record batches into Brain pages and graph edges using brain.py.
tools: ["read", "edit", "search", "shell"]
model: claude-haiku-4.5
---
```

**Behavior contract:**

1. Accept a bounded batch file or explicit record list.
2. For each record, identify durable entities, concepts, projects, companies,
   and relationships.
3. Run `brain.py add <type> "<name>" "<summary>"` for each page.
4. Fill all known frontmatter, State fields, descriptive sections, sources, and
   Open Threads; do not leave placeholders when source evidence exists.
5. Run `brain.py edge ...` for directional relationships.
6. Run `brain.py log ...` for dated timeline evidence.
7. Run `brain.py reindex` after direct markdown edits.
8. Report created pages, updated pages, edges, skipped records, and errors.

### brain-reviewer.agent.md

**Purpose:** Audit the Brain for completeness, consistency, connectivity, and
retrieval quality.

**Model:** `claude-sonnet-4.5`

**Use case:** Post-ingestion checks, periodic quality reviews, and pre-demo
validation.

```yaml
---
name: brain-reviewer
description: Audits Brain pages and graph structure for completeness, consistency, connectivity, and retrieval quality.
tools: ["read", "search", "shell"]
model: claude-sonnet-4.5
---
```

**Behavior contract:**

1. Run `brain.py stats`.
2. Run `brain.py audit-enrichment --limit=100`.
3. Check candidate distribution by type and identify highest-impact gaps.
4. Spot-check representative pages for placeholder summaries, missing sources,
   stale compiled truth, and weak timelines.
5. Check graph connectivity with `list`, `neighbors`, and targeted queries.
6. Report a structured verdict: `PASS`, `NEEDS ENRICHMENT`, or `NEEDS FIXES`.
7. Do not modify files unless explicitly asked to fix the findings.

### brain-dream.agent.md

**Purpose:** Perform bounded memory consolidation: find thin pages, enrich a
small high-value batch, update timelines, and reindex.

**Model:** `claude-sonnet-4.5`

**Use case:** Nightly or weekly maintenance.

```yaml
---
name: brain-dream
description: Runs bounded Brain maintenance by auditing enrichment candidates, enriching high-confidence pages, and reindexing.
tools: ["read", "edit", "search", "shell"]
model: claude-sonnet-4.5
---
```

**Behavior contract:**

1. Run `brain.py stats`.
2. Run `brain.py audit-enrichment --limit=50`.
3. Select a small batch, normally 5-10 pages, by score and likely evidence
   availability. Do not prioritize one type by default; use the audit score.
4. For each candidate, use the returned `suggested_evidence_sources`:
   - `brain graph neighbors`: inspect linked pages and related nodes.
   - `fts`: search existing markdown for the page name, aliases, project names,
     and related terms.
   - `workiq_search_people`: use for people or organization clues.
   - `workiq_search_emails`: use for durable context from subjects, sender
     domains, signatures, repeated threads, and concise body previews.
   - `workiq_list_events`: use for project context when calendar evidence is
     relevant.
5. Update only high-confidence durable facts. Keep weak claims as Open Threads.
6. Do not copy long private message text into markdown. Store concise derived
   facts with source references such as `email: Subject (YYYY-MM-DD)`.
7. Append dated timeline entries for enrichment work.
8. Run `brain.py reindex`.
9. Report pages changed, candidates skipped, evidence sources used, and remaining
   top gaps.

## Automations

Set automations up through Microsoft Scout's automation system (`m_create_automation`).

### Brain Dream

**Schedule:** Daily or weekly, depending on desired maintenance volume.

**Purpose:** Deterministically identify enrichment candidates, then perform a
bounded high-confidence enrichment pass.

Suggested automation prompt:

```text
Use the /brain skill. Run the default brain maintenance cycle:
1. Run `python $env:USERPROFILE\.copilot\m-skills\brain\brain.py stats`.
2. Run `python $env:USERPROFILE\.copilot\m-skills\brain\brain.py audit-enrichment --limit=50`.
3. Select up to 10 high-scoring candidates across all page types. Do not limit
   the pass to people pages unless the audit output justifies it.
4. For each selected candidate, gather the suggested evidence sources and enrich
   only high-confidence durable facts.
5. Update compiled truth, source references, Open Threads, and timeline entries.
6. Run `python $env:USERPROFILE\.copilot\m-skills\brain\brain.py reindex`.
7. Report changed pages, skipped pages, and remaining highest-scoring gaps.
```

### Brain Reindex Catch-up

**Schedule:** Temporary; every 30-60 minutes after bulk ingestion.

**Purpose:** Catch up vector embeddings after bulk data loads or rate limiting.

Suggested automation prompt:

```text
Run `python $env:USERPROFILE\.copilot\m-skills\brain\brain.py reindex`.
Report total, embedded, skipped, and errors. If embedded is 0 and errors is
empty for two consecutive runs, recommend disabling this temporary automation.
```

## Multi-Brain Support

Each brain is independent:

- `.graph.db` SQLite graph, FTS, and vectors
- Markdown vault files
- Embedding state
- `AGENTS.md`, `index.md`, `log.md`, and `_meta/` conventions

Agents and automations should always set the intended brain explicitly:

```powershell
# Default personal brain
python "$env:USERPROFILE\.copilot\m-skills\brain\brain.py" stats

# Named standalone brain
python "$env:USERPROFILE\.copilot\m-skills\brain\brain.py" --brain "$env:USERPROFILE\.brain-customer-a" stats
```

## Supervisor Pattern

Use this for large ingestion or cleanup jobs:

1. **Supervisor:** Splits work into bounded batches and assigns workers.
2. **Workers:** Process separate batches with `add`, direct markdown edits,
   `edge`, and `log`.
3. **Reviewer:** Runs `stats`, `audit-enrichment`, connectivity checks, and
   spot checks.
4. **Dream:** Performs ongoing small-batch consolidation after the initial load.

Workers can run in parallel when batches touch different pages. Use bounded
batches and report conflicts rather than overwriting uncertain changes.
