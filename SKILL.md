---
name: "brain"
description: "Personal knowledge graph (second brain). Add, relate, and query concepts stored as markdown in ~/.brain with a SQLite graph for relationships. Categories are fully dynamic — any type (people, projects, family, etc.) auto-creates its own folder."
---

## Second Brain Skill

A personal knowledge graph stored in `~/.brain/`. Markdown files are the content; SQLite is the relationship + vector layer. Page format follows the gbrain two-layer pattern: compiled truth + timeline.

### Storage Layout
```
~/.brain/
  .graph.db          # SQLite: graph (nodes + edges) + FTS5 + vec0 vectors
  brain.py           # Engine script
  people/            # Auto-created category folders
    blaine-perry.md
  projects/
    clawpilot.md
```

### Page Format (gbrain-inspired)

Every page has three sections:

```markdown
---
aliases: []
tags: []
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
Run with: `python ~/.brain/brain.py <command> [args...]`

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
| `stats` | | Show counts |

Node IDs: `type/slug` (e.g., `people/blaine-perry`, `projects/clawpilot`)

### How to Use This Skill

**When the user wants to remember something:**
1. Identify the entities and their types
2. `add <type> "<name>" "<summary>"` — creates page with template, summary goes in the `>` block
3. **Immediately read the file and fill in ALL fields you have data for:**
   - `aliases:` — known nicknames, alternate spellings, email handles
   - `tags:` — relevant categories (e.g., `[azure, ai, gov]`)
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
