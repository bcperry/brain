---
name: "brain"
description: "Personal knowledge graph (second brain). Uses a structured markdown vault in ~/.brain plus a SQLite graph/vector layer for relationships and embeddings."
---

## Second Brain Skill

A personal knowledge graph stored in `~/.brain/`. The markdown layer uses the structured Second Brain vault layout from the deck; SQLite remains the relationship + vector layer over those markdown files. Page format follows the gbrain two-layer pattern: compiled truth + timeline.


### Storage Layout
```
~/.brain/
  .graph.db          # SQLite: graph (nodes + edges) + FTS5 + vec0 vectors
  brain.py           # Engine script
  AGENTS.md          # Vault schema + operating rules
  README.md
  index.md           # Root catalog
  log.md             # Greppable dated activity log
  raw/               # Immutable source copies or references
  00-Inbox/          # Captures waiting for processing
  10-Notes/
    entities/
      people/
        blaine-perry.md
    concepts/
  20-Projects/
  30-Areas/
  40-Resources/
  50-Archive/
  _meta/
    conventions.md
    MOCs/
    templates/
```

### Markdown Vault Pattern

The default `/brain` implementation is a hybrid: the deck's structured
plain-markdown vault plus the existing `brain.py` SQLite graph/vector engine.
Markdown remains portable and Obsidian-friendly; `.graph.db` stores node
metadata, relationships, content hashes, and embeddings.

Deck-style vault layout:

```text
<vault>/
  AGENTS.md                  # Schema + operating rules; read first
  README.md
  index.md                   # Root catalog
  log.md                     # Greppable dated activity log
  raw/                       # Immutable source copies or references
  00-Inbox/                  # Captures waiting for processing
  10-Notes/
    entities/
    concepts/
  20-Projects/
  30-Areas/
  40-Resources/
  50-Archive/
  _meta/
    conventions.md
    MOCs/
    templates/
```

In this mode, create or update `AGENTS.md` and `_meta/conventions.md` before
writing many notes. `AGENTS.md` should define:

- Three layers and ownership: raw sources are immutable user-provided inputs,
  wiki pages are maintained by the assistant, schema/conventions are
  co-evolved with the user.
- Folder and naming rules: kebab-case atomic notes; dated inbox captures as
  `YYYY-MM-DD-slug`; use `[[wiki-links]]` for cross-references.
- Required YAML frontmatter for vault pages:

```yaml
---
title: "Page Title"
type: entity | concept | project | area | resource | moc | analysis | inbox
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: []
sources: []
status: draft | active | evergreen | archived
---
```

- Core operations:
  - `ingest`: read source fully; store source copy/reference in `raw/`; create
    a summary in `40-Resources/`; update entity/concept/project pages; update
    relevant MOCs, `index.md`, and `log.md`; report every touched page.
  - `query`: read `index.md` first; drill into linked pages; synthesize with
    citations to wiki pages; offer to save non-trivial answers as analysis
    pages.
  - `lint`: find contradictions, orphans, stale evergreen claims, implicit
    concepts, missing cross-references, and inbox backlog; report before
    fixing.
- House rules: one idea per page, cite sources, flag uncertainty, preserve raw
  inputs, and keep `log.md` dated and greppable.

Optional claims frontmatter block:

```yaml
claims:
  - id: claim-001
    text: "<assertion>"
    confidence: 0.0
    status: provisional | evergreen | disputed
    evidence:
      - source: raw/<file>
        kind: documentation | quote | observation
        excerpt: "<short quote>"
        captured: YYYY-MM-DD
        updated: YYYY-MM-DD
```

If claims are present, lint must flag disputed claims, no-evidence claims,
contradictions across pages, and stale evergreen claims.

### Hybrid Engine Behavior

- `init` creates the complete vault scaffold without removing `.graph.db`.
- `add` writes pages into the structured markdown folders and updates
  `index.md`, `log.md`, SQLite metadata, and the node embedding.
- `edge` continues to store relationships in SQLite.
- `query` continues to combine name search, keyword search, vector search, graph
  traversal, and markdown file reads.
- `migrate-vault` moves legacy root category folders into the structured layout,
  updates SQLite `file_path` values, and preserves old files under
  `50-Archive/legacy/`.
- `rebuild` recursively scans indexable vault markdown and re-registers/re-embeds
  pages into SQLite.

### Page Format (gbrain-inspired)

Every page has three sections:

```markdown
---
title: "Entity Name"
type: people
created: YYYY-MM-DD
updated: YYYY-MM-DD
aliases: []
tags: []
sources: []
status: active
---

# Entity Name

> Executive summary (one paragraph — the key thing to know)

## State
- **Role:** ...
- **Key context:** ...

## Open Threads
- Active items, pending follow-ups

---

## Timeline
- **2026-06-04** | Source — What happened.
- **2026-06-03** | Created — Page created.
```

**Above the line = Compiled Truth.** Always current. Rewritten when new info arrives.
**Below the line = Timeline.** Append-only, reverse-chronological evidence log.

### How It Works
- **Categories are dynamic**: Any type string becomes a folder.
- **Nodes** = a concept with a type, name, and markdown file
- **Edges** = directed relationships between any two nodes
- **Retrieval** = vector similarity + FTS keyword + name match → graph traversal → markdown content
- **Embeddings** = GitHub Models API (`text-embedding-3-small`, 1536d) via `gh auth token`

### Engine Commands
Run with: `python <skill-dir>/brain.py [--brain <path>] <command> [args...]`

The `<skill-dir>` is wherever this skill is installed (e.g., `~/.copilot/m-skills/brain/`).

Default data location: `~/.brain/`. Use `--brain <path>` to target a different brain.

| Command | Args | Description |
|---------|------|-------------|
| `add` | `<type> <name> [content]` | Create node (template) or update compiled truth. Auto-embeds. |
| `log` | `<type> <name> <entry>` | Append a timeline entry. Re-embeds. |
| `edge` | `<src_type> <src_name> <tgt_type> <tgt_name> <rel>` | Create a directed edge |
| `search` | `<query> [type]` | Find nodes by name (LIKE match) |
| `fts` | `<query>` | Full-text search across all markdown content |
| `vec` | `<query>` | Vector similarity search (semantic) |
| `neighbors` | `<node_id> [hops]` | Get a node's neighborhood |
| `read` | `<node_id>` | Read a node's markdown content |
| `query` | `<search_term> [hops]` | **Main retrieval**: vec + fts + name → traverse → content |
| `types` | | List all categories |
| `list` | `[type]` | List all nodes, optionally filtered by type |
| `delete` | `<node_id>` | Remove node, edges, vectors, and file |
| `reindex` | | Re-embed and re-index ALL nodes |
| `rebuild` | | Recursively scan structured vault markdown, re-register nodes, and re-embed |
| `migrate-vault` | | Move legacy root category pages into the structured markdown vault |
| `init` | | Create the vault scaffold (`AGENTS.md`, folders, index, log, metadata) |
| `stats` | | Show counts |

Node IDs: `type/slug` (e.g., `people/blaine-perry`, `projects/clawpilot`)

### Multi-Brain Support

The engine supports multiple independent brains. Default is `~/.brain/`.

```bash
# Personal brain (default)
python brain.py stats

# Standalone brain (separate data, separate graph, separate vectors)
python brain.py --brain ~/.brain-army stats
python brain.py --brain ~/.brain-army add units "1st Brigade" "Infantry brigade"
```

Alternatively, set the `BRAIN_DIR` environment variable.

Each brain is fully independent — its own `.graph.db`, markdown files, and vector embeddings.
The directory is auto-created on first use.

**When the user specifies a brain by name**, use `--brain <path>` on every command.
**When no brain is specified**, always use the default (`~/.brain/`).

### How to Use This Skill

**When the user wants to remember something:**
1. Identify the entities and their types
2. `add <type> "<name>" "<summary>"` — creates page with template, summary goes in the `>` block
3. **Immediately read the file and fill in ALL fields you have data for:**
   - frontmatter: `title`, `type`, `created`, `updated`, `aliases`, `tags`, `sources`, `status`
   - `aliases:` — known nicknames, alternate spellings, email handles
   - `tags:` — relevant categories (e.g., `[azure, ai, gov]`)
   - `sources:` — supporting files, URLs, emails, meetings, or user-provided context when known
   - Every State field (Role, Company, Status, Stack, etc.)
   - Descriptive sections (What They're Working On, What It Does, etc.)
   - Replace every `[No data yet]` with real content if you have it
   - Leave `[No data yet]` ONLY if you genuinely don't have that information
4. `edge ...` for each relationship
5. `log <type> "<name>" "<what happened>"` — adds a timeline entry with today's date
6. Run `reindex` after direct file edits

**The template is a checklist, not a final state.** Every `[No data yet]` is a prompt
for you to fill in. If the user says "remember John Smith, he's a PM at Contoso
working on their AI platform" — you fill in Role: PM, Company: Contoso,
What They're Working On: AI platform. Don't leave fields empty when you have the data.

**When the user wants to recall/query:**
1. `query "<search_term>"` — vector + FTS + graph traversal in one shot
2. Parse the JSON: `matches` (by source), `related_content` (markdown), `edges`
3. Synthesize a natural answer from retrieved content

**When the user wants to update a node:**
- To update the compiled truth (above the line): `add <type> "<name>" "<new_compiled_content>"`
  - This REPLACES compiled truth while preserving frontmatter and timeline
- To add a timeline event (below the line): `log <type> "<name>" "<source — what happened>"`
  - This APPENDS to timeline (never removes existing entries)
- To edit the markdown directly: edit the file, then run `reindex`

**When the user wants to explore:**
- `types` — show all categories
- `list <type>` — show all nodes in a category
- `neighbors "<node_id>" 2` — show 2-hop neighborhood
- `stats` — overview

### Type-Specific Templates

The engine uses different templates per type:
- **people** — State (role, company, relationship), What They're Working On, Open Threads
- **projects** — State (status, stack, team), What It Does, Key Decisions, Open Threads
- **companies** — State (what, stage, relationship), Key Context, Open Threads
- **concepts** — Core Idea, Why It Matters, See Also
- **_default** — State, Details, Open Threads

New templates can be added in brain.py's `TEMPLATES` dict. Unknown types use `_default`.

### Embedding Strategy — IMPORTANT
- **Each markdown file is embedded as ONE vector. No chunking.** Full file → single embedding.
- `add` and `log` both auto-re-embed the full file after changes.
- `reindex` re-reads and re-embeds ALL nodes. Safe to run anytime (idempotent).
- Token limit (~8191 for text-embedding-3-small) is the only constraint. Keep notes under ~6000 words.

### Relationship naming conventions
- Use lowercase kebab-case: `works-on`, `reports-to`, `related-to`, `member-of`
- Relationships are directional: "Alice works-on Project" not "Project works-on Alice"
- Common: `works-on`, `works-with`, `reports-to`, `member-of`, `related-to`, `depends-on`, `part-of`, `knows`, `mentors`

### Important Notes
- All output from brain.py is JSON — parse it before presenting to user
- `.graph.db` contains the graph, FTS5 index, AND vector embeddings
- Embeddings use GitHub Models API (free with Copilot license, rate-limited)
- If embedding fails, the node is still created — run `reindex` later
- Categories auto-create: any type string just works
- `[No data yet]` is a prompt to fill in — NEVER leave it if you have the data
- When updating a node, re-read the file and fill any newly-knowable fields
- Corrections are high-value: if user corrects something, update immediately
