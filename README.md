# Brain

A lightweight personal knowledge graph for AI agents. Markdown files are the source of truth; SQLite provides the relationship graph and vector search layer.

Inspired by [gbrain](https://github.com/garrytan/gbrain), but built to be minimal and self-contained — no Postgres, no external services, no daemon. Just Python, SQLite, and your filesystem.

## How It Works

```
<this-repo>/                 ← Code (skill + engine)
  SKILL.md                    Skill instructions for Clawpilot / AI agents
  brain.py                    Engine (graph, embeddings, file ops)
  serve.py                    HTTP API for the browser-based explorer
  brain-explorer.html         Browser UI (graph viewer + search)

~/.brain/                    ← Default data directory
  .graph.db                   SQLite: nodes, edges, vectors (sqlite-vec)
  AGENTS.md                   Vault schema + operating rules
  README.md
  index.md                    Root catalog
  log.md                      Greppable dated activity log
  raw/ 00-Inbox/ 50-Archive/
  10-Notes/entities/          Entity pages grouped by type
  10-Notes/concepts/          Concept pages
  20-Projects/ 30-Areas/ 40-Resources/
  _meta/conventions.md _meta/MOCs/ _meta/templates/
```

**Principles:**
- Content lives ONLY in markdown files — the DB stores metadata + vectors, never content
- Each markdown file is embedded as ONE vector (no chunking)
- Categories are fully dynamic — any type string auto-creates a folder under the structured vault
- Pages use a two-layer format: compiled truth (above `---`) + append-only timeline (below)

## Structured Markdown Vault + SQLite

The default implementation combines the companion deck's structured
plain-markdown vault with the existing SQLite graph/vector engine:

```text
<vault>/
  AGENTS.md README.md index.md log.md
  raw/ 00-Inbox/ 50-Archive/
  10-Notes/entities/ 10-Notes/concepts/
  20-Projects/ 30-Areas/ 40-Resources/
  _meta/conventions.md _meta/MOCs/ _meta/templates/
```

Markdown stays portable and Obsidian-friendly. SQLite keeps node metadata,
edges, content hashes, and embeddings. `brain.py add` writes pages into the
structured folders, updates `index.md` and `log.md`, and embeds the markdown
file as one vector.

## Requirements

- Python 3.10+
- `sqlite-vec` — `pip install sqlite-vec`
- `gh` CLI authenticated — embeddings use GitHub Models API (free with Copilot license)

## Quick Start

```bash
# Create your first node (data goes to ~/.brain/ by default)
# The vault scaffold is created automatically, or explicitly with: python brain.py init
python brain.py add people "Jane Smith" "VP Engineering at Acme Corp"

# Add a relationship
python brain.py edge people "Jane Smith" companies "Acme Corp" works-at

# Query (vector + keyword + graph traversal)
python brain.py query "who works at Acme"

# Check stats
python brain.py stats
```

## Multiple Brains

By default, all data goes to `~/.brain/`. To use a separate standalone brain (e.g., for a specific domain), use the `--brain` flag:

```bash
# Use a different brain
python brain.py --brain ~/.brain-customer-a add companies "Acme Corp" "Customer account"
python brain.py --brain ~/.brain-customer-a stats

# Or set via environment variable
export BRAIN_DIR=~/.brain-customer-a
python brain.py stats
```

Each brain is fully independent — its own `.graph.db`, its own markdown files, its own vector embeddings. The `--brain` flag (or `BRAIN_DIR` env var) can be passed to any command including `serve.py`:

```bash
# Explore a specific brain in the browser
BRAIN_DIR=~/.brain-customer-a python serve.py
```

The flag works with any path. The directory is auto-created on first use.

## Commands

All commands accept an optional `--brain <path>` flag before the command name.

| Command | Args | Description |
|---------|------|-------------|
| `add` | `<type> <name> [summary]` | Create/update a node. Auto-embeds. |
| `log` | `<type> <name> <entry>` | Append a timeline entry. Re-embeds. |
| `edge` | `<src_type> <src_name> <tgt_type> <tgt_name> <rel>` | Create a directed edge |
| `search` | `<query> [type]` | Find nodes by name |
| `fts` | `<query>` | Keyword search across file content |
| `vec` | `<query>` | Vector similarity search |
| `query` | `<query> [hops]` | Full retrieval: vec + keyword + graph traversal |
| `neighbors` | `<node_id> [hops]` | Graph neighborhood |
| `read` | `<node_id>` | Read a node's markdown |
| `list` | `[type]` | List nodes |
| `types` | | List all categories |
| `delete` | `<node_id>` | Remove node, edges, vectors, and file |
| `audit-enrichment` | `[--limit=N] [--type=<type>]` | Deterministically scan markdown pages and return scored enrichment candidates |
| `reindex` | | Re-embed all nodes from their files |
| `rebuild` | | Scan filesystem, re-register + re-embed all (use after DB wipe) |
| `init` | | Create the structured vault scaffold |
| `migrate-vault` | | Move legacy root category pages into the structured vault |
| `stats` | | Show counts |

## Page Format

```markdown
---
title: "Jane Smith"
type: people
created: 2026-06-01
updated: 2026-06-04
aliases: [Jenny, jen@acme.com]
tags: [engineering, leadership]
sources: []
status: active
---

# Jane Smith

> VP Engineering at Acme Corp. Leading their AI platform team.

## State
- **Role:** VP Engineering
- **Company:** Acme Corp
- **Relationship:** Customer contact
- **Key context:** Decision maker for our enterprise deal

## What They're Working On
Building an internal AI platform for their 500-person eng org.

## Open Threads
- Waiting on security review for new pricing tier

---

## Timeline
- **2026-06-04** | Meeting — Discussed Q3 roadmap priorities.
- **2026-05-22** | Email — Sent pricing proposal for 500-seat tier.
- **2026-06-01** | Created — Page created.
```

## Browser Explorer

Start the API server and open `brain-explorer.html`:

```bash
# Default brain
python serve.py

# Specific brain
BRAIN_DIR=~/.brain-customer-a python serve.py
```

The explorer runs at `http://localhost:7433` and includes:
- **Search tab** — vector similarity, keyword, name matching with scores
- **Graph tab** — interactive force-directed visualization of nodes and edges

## Embeddings

Uses GitHub Models API (`text-embedding-3-small`, 1536 dimensions) authenticated via `gh auth token`. Free with GitHub Copilot license, rate-limited.

The vector table uses [sqlite-vec](https://github.com/asg017/sqlite-vec) for KNN search directly in SQLite — no external vector DB needed.

## As a Clawpilot Skill

Drop this repo into `~/.copilot/m-skills/brain/` and invoke with `/brain`. The `SKILL.md` file contains full instructions for the AI agent on how to use the brain — when to add nodes, how to fill templates, when to re-embed, etc.

## License

MIT
