"""
Second Brain - Lightweight knowledge graph backed by markdown + SQLite.
Categories are fully dynamic: any type string becomes a folder.
Vector search via sqlite-vec + GitHub Models embeddings.
Page format: frontmatter + compiled truth + timeline (gbrain-inspired).

PRINCIPLE: Content lives ONLY in markdown files. The DB stores only:
  - nodes: id, type, name, file_path, timestamps
  - edges: source_id, target_id, relationship
  - vec_nodes: node_id, embedding vector
"""

import sqlite3
import os
import json
import re
import sys
import struct
import hashlib
import subprocess
import time
from pathlib import Path
from datetime import datetime

try:
    import sqlite_vec
    HAS_VEC = True
except ImportError:
    HAS_VEC = False

# Multi-brain support: set BRAIN_DIR env var or pass --brain <path> to override
BRAIN_DIR = Path(os.environ.get("BRAIN_DIR", str(Path.home() / ".brain")))
DB_PATH = BRAIN_DIR / ".graph.db"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
EMBED_URL = "https://models.inference.ai.azure.com/embeddings"
EMBED_BATCH_SIZE = 20  # texts per API call (GitHub Models limit)
EMBED_RETRY_MAX = 5
EMBED_RETRY_BASE_DELAY = 2.0  # seconds, doubled each retry

VAULT_DIRS = [
    "raw",
    "00-Inbox",
    "10-Notes/entities",
    "10-Notes/concepts",
    "20-Projects",
    "30-Areas",
    "40-Resources",
    "50-Archive",
    "_meta/MOCs",
    "_meta/templates",
]

ENTITY_TYPES = {
    "people", "person", "companies", "company", "organizations", "organization",
    "orgs", "org", "customers", "customer", "products", "product", "teams",
    "team", "units", "unit", "entities", "entity",
}
CONCEPT_TYPES = {"concepts", "concept", "ideas", "idea", "topics", "topic"}
PROJECT_TYPES = {"projects", "project"}
AREA_TYPES = {"areas", "area"}
RESOURCE_TYPES = {"resources", "resource", "summaries", "summary", "analysis", "analyses"}

# --- Page Templates ---

TEMPLATES = {
    "people": """---
title: "{name}"
type: people
created: {date}
updated: {date}
aliases: []
tags: []
sources: []
status: active
---

# {name}

> [Executive summary — who they are, why they matter]

## State
- **Role:** [No data yet]
- **Company:** [No data yet]
- **Relationship:** [No data yet]
- **Key context:** [No data yet]

## What They're Working On
[No data yet]

## Open Threads
[None]

---

## Timeline
- **{date}** | Created — Page created.
""",
    "projects": """---
title: "{name}"
type: projects
created: {date}
updated: {date}
aliases: []
tags: []
sources: []
status: active
---

# {name}

> [Executive summary — what it is, why it matters]

## State
- **Status:** Active
- **Stack:** [No data yet]
- **Team:** [No data yet]

## What It Does
[No data yet]

## Key Decisions
[None yet]

## Open Threads
[None]

---

## Timeline
- **{date}** | Created — Page created.
""",
    "companies": """---
title: "{name}"
type: companies
created: {date}
updated: {date}
aliases: []
tags: []
sources: []
status: active
---

# {name}

> [Executive summary — what they do, stage, why they matter]

## State
- **What:** [No data yet]
- **Stage:** [No data yet]
- **Relationship:** [No data yet]

## Key Context
[No data yet]

## Open Threads
[None]

---

## Timeline
- **{date}** | Created — Page created.
""",
    "concepts": """---
title: "{name}"
type: concepts
created: {date}
updated: {date}
aliases: []
tags: []
sources: []
status: active
---

# {name}

> [One-paragraph distillation of this concept]

## Core Idea
[No data yet]

## Why It Matters
[No data yet]

## See Also
[None yet]

---

## Timeline
- **{date}** | Created — Page created.
""",
    "_default": """---
title: "{name}"
type: {node_type}
created: {date}
updated: {date}
aliases: []
tags: []
sources: []
status: active
---

# {name}

> [Summary]

## Details
[No data yet]

## Open Threads
[None]

---

## Timeline
- **{date}** | Created — Page created.
"""
}


def get_template(node_type: str, name: str) -> str:
    t = slugify(node_type)
    template = TEMPLATES.get(t, TEMPLATES["_default"])
    date = datetime.now().strftime("%Y-%m-%d")
    return template.format(name=name, node_type=t, date=date)


def parse_page(content: str) -> dict:
    """Parse a brain page into frontmatter, compiled truth, and timeline."""
    parts = {"frontmatter": "", "compiled": "", "timeline": ""}
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            parts["frontmatter"] = content[3:end].strip()
            content = content[end + 3:].strip()
    timeline_match = re.search(r'\n---\s*\n(## Timeline.*)', content, re.DOTALL)
    if timeline_match:
        parts["compiled"] = content[:timeline_match.start()].strip()
        parts["timeline"] = timeline_match.group(1).strip()
    else:
        parts["compiled"] = content.strip()
    return parts


def update_compiled_truth(existing_content: str, new_content: str) -> str:
    """Replace compiled truth, preserve frontmatter and timeline."""
    parts = parse_page(existing_content)
    result = ""
    if parts["frontmatter"]:
        frontmatter = set_frontmatter_field(parts["frontmatter"], "updated", datetime.now().strftime("%Y-%m-%d"))
        result += f"---\n{frontmatter}\n---\n\n"
    result += new_content.strip()
    if parts["timeline"]:
        result += f"\n\n---\n\n{parts['timeline']}"
    return result


def set_frontmatter_field(frontmatter: str, key: str, value: str) -> str:
    """Set a simple scalar YAML frontmatter field without requiring a YAML dependency."""
    pattern = rf"^{re.escape(key)}:\s*.*$"
    replacement = f"{key}: {value}"
    if re.search(pattern, frontmatter, flags=re.MULTILINE):
        return re.sub(pattern, replacement, frontmatter, count=1, flags=re.MULTILINE)
    return f"{frontmatter.rstrip()}\n{replacement}"


def append_timeline(file_path: Path, entry: str):
    """Append an entry to the timeline section."""
    content = file_path.read_text(encoding="utf-8")
    date = datetime.now().strftime("%Y-%m-%d")
    timeline_entry = f"- **{date}** | {entry}"
    timeline_match = re.search(r'(## Timeline\n)', content)
    if timeline_match:
        insert_pos = timeline_match.end()
        content = content[:insert_pos] + timeline_entry + "\n" + content[insert_pos:]
    else:
        content += f"\n\n---\n\n## Timeline\n{timeline_entry}\n"
    if content.startswith("---"):
        parts = parse_page(content)
        frontmatter = set_frontmatter_field(parts["frontmatter"], "updated", date)
        content = f"---\n{frontmatter}\n---\n\n{parts['compiled']}"
        if parts["timeline"]:
            content += f"\n\n---\n\n{parts['timeline']}"
    file_path.write_text(content, encoding="utf-8")


# --- Database (metadata + vectors only, NO content) ---

def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")

    if HAS_VEC:
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)

    db.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id, relationship),
            FOREIGN KEY (source_id) REFERENCES nodes(id),
            FOREIGN KEY (target_id) REFERENCES nodes(id)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")

    # Add content_hash column for skip-unchanged optimization (idempotent migration)
    try:
        db.execute("ALTER TABLE nodes ADD COLUMN content_hash TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists

    if HAS_VEC:
        db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_nodes USING vec0(
                node_id TEXT PRIMARY KEY,
                embedding float[{EMBED_DIM}]
            )
        """)

    db.commit()
    return db


# --- Utilities ---

def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    return s.strip('-')


def node_id(node_type: str, name: str) -> str:
    return f"{slugify(node_type)}/{slugify(name)}"


def write_if_missing(path: Path, content: str):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def ensure_vault_structure():
    """Create the deck-style markdown vault scaffold while preserving .graph.db."""
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    for rel in VAULT_DIRS:
        (BRAIN_DIR / rel).mkdir(parents=True, exist_ok=True)

    write_if_missing(BRAIN_DIR / "AGENTS.md", """# Second Brain AGENTS.md

## Layers and ownership
- `raw/` contains immutable source copies or references.
- Wiki pages are maintained by the assistant as compiled knowledge.
- Schema and conventions are co-evolved with the user.

## Core operations
- Ingest: read sources fully, preserve source references, update related pages, MOCs, `index.md`, and `log.md`.
- Query: read `index.md`, drill into linked pages, synthesize with citations to wiki pages.
- Lint: report contradictions, orphans, stale evergreen claims, implicit concepts, missing links, and inbox backlog before fixing.
""")
    write_if_missing(BRAIN_DIR / "README.md", "# Second Brain\n\nPlain markdown vault with SQLite graph and vector embeddings in `.graph.db`.\n")
    write_if_missing(BRAIN_DIR / "index.md", "# Second Brain Index\n\n## Entities\n\n## Concepts\n\n## Projects\n\n## Areas\n\n## Resources\n\n## MOCs\n")
    write_if_missing(BRAIN_DIR / "log.md", "# Second Brain Log\n\n")
    write_if_missing(BRAIN_DIR / "_meta" / "conventions.md", """# Conventions

- Use kebab-case filenames for atomic notes.
- Use `YYYY-MM-DD-slug.md` for inbox captures.
- Use `[[wiki-links]]` for cross-references.
- Keep one idea per page and cite sources when known.
""")
    write_if_missing(BRAIN_DIR / "_meta" / "MOCs" / "home.md", """---
title: "Home"
type: moc
created: {date}
updated: {date}
tags: []
sources: []
status: active
---

# Home

## Key entry points
- [[../../index]]
""".format(date=datetime.now().strftime("%Y-%m-%d")))


def category_base_dir(node_type: str) -> Path:
    t = slugify(node_type)
    if t in CONCEPT_TYPES:
        return BRAIN_DIR / "10-Notes" / "concepts"
    if t in PROJECT_TYPES:
        return BRAIN_DIR / "20-Projects"
    if t in AREA_TYPES:
        return BRAIN_DIR / "30-Areas"
    if t in RESOURCE_TYPES:
        return BRAIN_DIR / "40-Resources"
    return BRAIN_DIR / "10-Notes" / "entities"


def ensure_category_dir(node_type: str) -> Path:
    ensure_vault_structure()
    t = slugify(node_type)
    base = category_base_dir(t)
    if t in PROJECT_TYPES or t in AREA_TYPES or t in RESOURCE_TYPES:
        d = base
    elif t in CONCEPT_TYPES:
        d = base
    else:
        d = base / t
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_vault_log(action: str, nid: str, rel_path: str):
    ensure_vault_structure()
    date = datetime.now().strftime("%Y-%m-%d")
    with (BRAIN_DIR / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"- **{date}** | {action} | {nid} | {rel_path}\n")


def update_index_entry(node_type: str, name: str, rel_path: str):
    ensure_vault_structure()
    index_path = BRAIN_DIR / "index.md"
    content = index_path.read_text(encoding="utf-8")
    t = slugify(node_type)
    section = "Entities"
    if t in CONCEPT_TYPES:
        section = "Concepts"
    elif t in PROJECT_TYPES:
        section = "Projects"
    elif t in AREA_TYPES:
        section = "Areas"
    elif t in RESOURCE_TYPES:
        section = "Resources"

    link_target = rel_path.replace("\\", "/").removesuffix(".md")
    entry = f"- [[{link_target}|{name}]]"
    if entry in content:
        return

    header = f"## {section}"
    if header not in content:
        content = content.rstrip() + f"\n\n{header}\n"

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == header:
            insert_at = i + 1
            while insert_at < len(lines) and not lines[insert_at].startswith("## "):
                insert_at += 1
            lines.insert(insert_at, entry)
            index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            return


def parse_frontmatter_field(content: str, key: str) -> str | None:
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    frontmatter = content[3:end]
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def infer_type_from_path(md_file: Path, content: str) -> str:
    frontmatter_type = parse_frontmatter_field(content, "type")
    if frontmatter_type:
        return slugify(frontmatter_type)

    rel = md_file.relative_to(BRAIN_DIR)
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "10-Notes" and parts[1] == "entities":
        return slugify(parts[2]) if len(parts) > 3 else "entities"
    if len(parts) >= 2 and parts[0] == "10-Notes" and parts[1] == "concepts":
        return "concepts"
    if parts[0] == "20-Projects":
        return "projects"
    if parts[0] == "30-Areas":
        return "areas"
    if parts[0] == "40-Resources":
        return "resources"
    if parts[0] == "00-Inbox":
        return "inbox"
    if len(parts) >= 2 and parts[0] == "_meta" and parts[1] == "MOCs":
        return "moc"
    return slugify(md_file.parent.name)


def is_indexable_markdown(md_file: Path) -> bool:
    rel = md_file.relative_to(BRAIN_DIR)
    if any(part.startswith(".") for part in rel.parts):
        return False
    if rel.parts[0] in {"raw", "50-Archive"}:
        return False
    if len(rel.parts) == 1 and rel.name in {"AGENTS.md", "README.md", "log.md"}:
        return False
    if len(rel.parts) >= 2 and rel.parts[0] == "_meta" and rel.parts[1] in {"templates"}:
        return False
    if rel == Path("_meta") / "conventions.md":
        return False
    return md_file.suffix.lower() == ".md"


def get_gh_token() -> str:
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception:
        return ""


def get_embeddings(texts: list) -> list:
    """Call embeddings API with exponential backoff on rate limits."""
    token = get_gh_token()
    if not token:
        raise RuntimeError("No GitHub token. Run 'gh auth login'.")
    import urllib.request, urllib.error
    payload = json.dumps({"input": texts, "model": EMBED_MODEL}).encode()
    req_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for attempt in range(EMBED_RETRY_MAX):
        req = urllib.request.Request(EMBED_URL, data=payload, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return [item["embedding"] for item in data["data"]]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < EMBED_RETRY_MAX - 1:
                delay = EMBED_RETRY_BASE_DELAY * (2 ** attempt)
                retry_after = e.headers.get("Retry-After")
                if retry_after:
                    delay = max(delay, float(retry_after))
                time.sleep(delay)
            else:
                raise


def serialize_f32(vec: list) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def content_hash(text: str) -> str:
    """SHA-256 of content — used to skip re-embedding unchanged nodes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_node(db, nid: str, content: str):
    """Embed full file content as a single vector."""
    if not HAS_VEC or not content.strip():
        return
    embeddings = get_embeddings([content])
    vec_bytes = serialize_f32(embeddings[0])
    db.execute("DELETE FROM vec_nodes WHERE node_id = ?", (nid,))
    db.execute("INSERT INTO vec_nodes (node_id, embedding) VALUES (?, ?)", (nid, vec_bytes))
    db.commit()


def embed_batch(db, items: list[tuple[str, str]]) -> dict:
    """Embed multiple (nid, content) pairs in batches. Returns stats dict."""
    if not HAS_VEC or not items:
        return {"embedded": 0, "skipped": 0, "errors": []}

    results = {"embedded": 0, "skipped": 0, "errors": []}

    for i in range(0, len(items), EMBED_BATCH_SIZE):
        batch = items[i:i + EMBED_BATCH_SIZE]
        texts = [content for _, content in batch]
        nids = [nid for nid, _ in batch]

        try:
            embeddings = get_embeddings(texts)
            for nid, vec in zip(nids, embeddings):
                vec_bytes = serialize_f32(vec)
                db.execute("DELETE FROM vec_nodes WHERE node_id = ?", (nid,))
                db.execute("INSERT INTO vec_nodes (node_id, embedding) VALUES (?, ?)", (nid, vec_bytes))
                # Store content hash so we can skip next time
                chash = content_hash(next(c for n, c in batch if n == nid))
                db.execute("UPDATE nodes SET content_hash = ? WHERE id = ?", (chash, nid))
            db.commit()
            results["embedded"] += len(batch)
        except Exception as e:
            results["errors"].append(f"batch {i//EMBED_BATCH_SIZE}: {str(e)}")
            # Try individually as fallback so one bad item doesn't kill the batch
            for nid, txt in batch:
                try:
                    embed_node(db, nid, txt)
                    db.execute("UPDATE nodes SET content_hash = ? WHERE id = ?", (content_hash(txt), nid))
                    db.commit()
                    results["embedded"] += 1
                except Exception as e2:
                    results["errors"].append(f"{nid}: {str(e2)}")

    return results


# --- Core Operations ---

def add_node(node_type: str, name: str, content: str = "", embed: bool = True) -> dict:
    db = get_db()
    nid = node_id(node_type, name)
    slug = slugify(name)
    cat_dir = ensure_category_dir(node_type)
    file_path = cat_dir / f"{slug}.md"
    now = datetime.now().isoformat()
    created_file = False

    if not file_path.exists():
        page = get_template(node_type, name)
        if content:
            page = re.sub(r'> \[.*?\]', f'> {content}', page, count=1)
        file_path.write_text(page, encoding="utf-8")
        created_file = True
    elif content:
        existing = file_path.read_text(encoding="utf-8")
        updated = update_compiled_truth(existing, content)
        file_path.write_text(updated, encoding="utf-8")

    rel_path = str(file_path.relative_to(BRAIN_DIR))
    existing_node = db.execute("SELECT id FROM nodes WHERE id = ?", (nid,)).fetchone()
    if existing_node:
        db.execute("UPDATE nodes SET file_path = ?, updated_at = ? WHERE id = ?", (rel_path, now, nid))
    else:
        db.execute(
            "INSERT INTO nodes (id, type, name, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (nid, slugify(node_type), name, rel_path, now, now)
        )
    db.commit()
    update_index_entry(node_type, name, rel_path)
    append_vault_log("Created" if created_file else "Updated", nid, rel_path)

    if embed:
        full_content = file_path.read_text(encoding="utf-8")
        try:
            embed_node(db, nid, full_content)
            db.execute("UPDATE nodes SET content_hash = ? WHERE id = ?", (content_hash(full_content), nid))
            db.commit()
        except Exception as e:
            return {"id": nid, "type": node_type, "name": name, "file": rel_path, "embed_error": str(e)}

    return {"id": nid, "type": node_type, "name": name, "file": rel_path, "embedded": embed}


def log_event(node_type: str, name: str, entry: str) -> dict:
    """Append a timeline entry, re-embed."""
    db = get_db()
    nid = node_id(node_type, name)
    node = db.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
    if not node:
        return {"error": f"Node not found: {nid}. Create it first with 'add'."}

    file_path = BRAIN_DIR / node["file_path"]
    if not file_path.exists():
        return {"error": f"File not found: {node['file_path']}"}

    append_timeline(file_path, entry)

    now = datetime.now().isoformat()
    db.execute("UPDATE nodes SET updated_at = ? WHERE id = ?", (now, nid))
    db.commit()

    full_content = file_path.read_text(encoding="utf-8")
    try:
        embed_node(db, nid, full_content)
        db.execute("UPDATE nodes SET content_hash = ? WHERE id = ?", (content_hash(full_content), nid))
        db.commit()
    except Exception as e:
        return {"id": nid, "logged": entry, "embed_error": str(e)}

    append_vault_log("Timeline", nid, node["file_path"])
    return {"id": nid, "logged": entry}


def add_edge(source_type: str, source_name: str, target_type: str, target_name: str, relationship: str) -> dict:
    db = get_db()
    sid = node_id(source_type, source_name)
    tid = node_id(target_type, target_name)
    now = datetime.now().isoformat()

    if not db.execute("SELECT id FROM nodes WHERE id = ?", (sid,)).fetchone():
        add_node(source_type, source_name, embed=False)
    if not db.execute("SELECT id FROM nodes WHERE id = ?", (tid,)).fetchone():
        add_node(target_type, target_name, embed=False)

    db.execute(
        "INSERT OR IGNORE INTO edges (source_id, target_id, relationship, created_at) VALUES (?, ?, ?, ?)",
        (sid, tid, relationship, now)
    )
    db.commit()
    return {"source": sid, "target": tid, "relationship": relationship}


# --- Search ---

def search(query: str, node_type: str = None, limit: int = 20) -> list:
    """Search nodes by name."""
    db = get_db()
    q = f"%{query}%"
    if node_type:
        rows = db.execute(
            "SELECT * FROM nodes WHERE type = ? AND name LIKE ? LIMIT ?",
            (slugify(node_type), q, limit)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM nodes WHERE name LIKE ? OR id LIKE ? LIMIT ?",
            (q, q, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def fts_search(query: str, limit: int = 10) -> list:
    """Keyword search by reading markdown files directly. No content in DB."""
    db = get_db()
    nodes = db.execute("SELECT id, file_path FROM nodes").fetchall()
    results = []
    terms = query.lower().split()

    for node in nodes:
        fp = BRAIN_DIR / node["file_path"]
        if not fp.exists():
            continue
        content = fp.read_text(encoding="utf-8").lower()
        if any(term in content for term in terms):
            for term in terms:
                idx = content.find(term)
                if idx != -1:
                    start = max(0, idx - 40)
                    end = min(len(content), idx + len(term) + 40)
                    snippet = content[start:end].replace("\n", " ")
                    results.append({"node_id": node["id"], "snippet": f"...{snippet}..."})
                    break
        if len(results) >= limit:
            break

    return results


def vec_search(query: str, limit: int = 10) -> list:
    """Vector similarity search."""
    if not HAS_VEC:
        return [{"error": "sqlite-vec not installed"}]
    db = get_db()
    embeddings = get_embeddings([query])
    query_vec = serialize_f32(embeddings[0])
    rows = db.execute(
        "SELECT node_id, distance FROM vec_nodes WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (query_vec, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def get_neighbors(nid: str, hops: int = 1) -> dict:
    """Get node and its neighbors up to N hops."""
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
    if not node:
        return {"error": f"Node not found: {nid}"}

    visited = {nid}
    frontier = [nid]
    edges_found = []

    for _ in range(hops):
        next_frontier = []
        for current in frontier:
            outgoing = db.execute(
                "SELECT * FROM edges WHERE source_id = ? OR target_id = ?",
                (current, current)
            ).fetchall()
            for e in outgoing:
                edges_found.append(dict(e))
                neighbor = e["target_id"] if e["source_id"] == current else e["source_id"]
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier

    nodes = []
    for vid in visited:
        n = db.execute("SELECT * FROM nodes WHERE id = ?", (vid,)).fetchone()
        if n:
            nodes.append(dict(n))

    return {"center": dict(node), "nodes": nodes, "edges": edges_found}


def read_node_content(nid: str) -> str:
    """Read a node's markdown file."""
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
    if not node:
        return f"Node not found: {nid}"
    fp = BRAIN_DIR / node["file_path"]
    if fp.exists():
        return fp.read_text(encoding="utf-8")
    return f"File not found: {node['file_path']}"


def list_types() -> list:
    db = get_db()
    rows = db.execute("SELECT DISTINCT type FROM nodes ORDER BY type").fetchall()
    return [r["type"] for r in rows]


def list_nodes(node_type: str = None) -> list:
    db = get_db()
    if node_type:
        rows = db.execute(
            "SELECT id, type, name, file_path FROM nodes WHERE type = ? ORDER BY name",
            (slugify(node_type),)
        ).fetchall()
    else:
        rows = db.execute("SELECT id, type, name, file_path FROM nodes ORDER BY type, name").fetchall()
    return [dict(r) for r in rows]


def delete_node(nid: str) -> dict:
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
    if not node:
        return {"error": "Node not found"}
    db.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (nid, nid))
    db.execute("DELETE FROM nodes WHERE id = ?", (nid,))
    if HAS_VEC:
        db.execute("DELETE FROM vec_nodes WHERE node_id = ?", (nid,))
    db.commit()
    fp = BRAIN_DIR / node["file_path"]
    if fp.exists():
        fp.unlink()
    return {"deleted": nid}


# --- Retrieval ---

def query_related(query: str, hops: int = 2, use_vec: bool = True) -> dict:
    """Main retrieval: vector + keyword + name → graph traversal → file content."""
    name_matches = search(query)
    fts_matches = fts_search(query)

    candidates = set()
    for m in name_matches[:5]:
        candidates.add(m["id"])
    for m in fts_matches[:5]:
        candidates.add(m["node_id"])

    vec_results = []
    if use_vec and HAS_VEC:
        try:
            vec_results = vec_search(query, limit=5)
            for v in vec_results:
                candidates.add(v["node_id"])
        except Exception as e:
            vec_results = [{"error": str(e)}]

    all_nodes = set()
    all_edges = []
    for nid in list(candidates)[:10]:
        graph = get_neighbors(nid, hops=hops)
        if "error" not in graph:
            for n in graph.get("nodes", []):
                all_nodes.add(n["id"])
            all_edges.extend(graph.get("edges", []))

    contents = {}
    for nid in all_nodes:
        contents[nid] = read_node_content(nid)

    unique_edges = list({(e["source_id"], e["target_id"], e["relationship"]): e for e in all_edges}.values())

    return {
        "matches": {"name": name_matches[:5], "keyword": fts_matches[:5], "vector": vec_results[:5]},
        "related_content": contents,
        "edges": unique_edges
    }


# --- Maintenance ---

def reindex_all(force: bool = False) -> dict:
    """Re-embed nodes from their markdown files. Skips unchanged content unless force=True."""
    db = get_db()
    nodes = db.execute("SELECT id, file_path, content_hash FROM nodes").fetchall()
    results = {"total": len(nodes), "embedded": 0, "skipped": 0, "errors": []}

    to_embed = []
    for node in nodes:
        nid = node["id"]
        fp = BRAIN_DIR / node["file_path"]
        if not fp.exists():
            results["errors"].append(f"{nid}: file not found")
            continue
        file_content = fp.read_text(encoding="utf-8")
        if not file_content.strip():
            results["skipped"] += 1
            continue
        # Skip if content hasn't changed
        chash = content_hash(file_content)
        if not force and node["content_hash"] == chash:
            results["skipped"] += 1
            continue
        to_embed.append((nid, file_content))

    if to_embed and HAS_VEC:
        batch_results = embed_batch(db, to_embed)
        results["embedded"] = batch_results["embedded"]
        results["errors"].extend(batch_results["errors"])

    return results


def stats() -> dict:
    ensure_vault_structure()
    db = get_db()
    node_count = db.execute("SELECT COUNT(*) as c FROM nodes").fetchone()["c"]
    edge_count = db.execute("SELECT COUNT(*) as c FROM edges").fetchone()["c"]
    vec_count = 0
    if HAS_VEC:
        try:
            vec_count = db.execute("SELECT COUNT(*) as c FROM vec_nodes").fetchone()["c"]
        except:
            pass
    types = list_types()
    return {
        "nodes": node_count,
        "edges": edge_count,
        "vec_embedded": vec_count,
        "types": types,
        "has_vec": HAS_VEC
    }


def init_vault() -> dict:
    ensure_vault_structure()
    return {
        "brain": str(BRAIN_DIR),
        "database": str(DB_PATH),
        "created": VAULT_DIRS + ["AGENTS.md", "README.md", "index.md", "log.md", "_meta/conventions.md", "_meta/MOCs/home.md"]
    }




def rebuild() -> dict:
    """Scan filesystem, re-register all nodes, and re-embed. Use after DB deletion."""
    ensure_vault_structure()
    db = get_db()
    results = {"found": 0, "registered": 0, "embedded": 0, "errors": []}
    to_embed = []

    for md_file in BRAIN_DIR.rglob("*.md"):
        if not is_indexable_markdown(md_file):
            continue
        results["found"] += 1
        file_content = md_file.read_text(encoding="utf-8")
        node_type = infer_type_from_path(md_file, file_content)

        name_match = re.search(r'^#\s+(.+)$', file_content, re.MULTILINE)
        frontmatter_title = parse_frontmatter_field(file_content, "title")
        name = name_match.group(1).strip() if name_match else (frontmatter_title or md_file.stem)

        nid = node_id(node_type, name)
        rel_path = str(md_file.relative_to(BRAIN_DIR))
        now = datetime.now().isoformat()

        existing = db.execute("SELECT id FROM nodes WHERE id = ?", (nid,)).fetchone()
        if existing:
            db.execute(
                "UPDATE nodes SET type = ?, name = ?, file_path = ?, updated_at = ? WHERE id = ?",
                (slugify(node_type), name, rel_path, now, nid)
            )
        else:
            db.execute(
                "INSERT INTO nodes (id, type, name, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (nid, slugify(node_type), name, rel_path, now, now)
            )
        results["registered"] += 1

        if file_content.strip():
            to_embed.append((nid, file_content))

    db.commit()

    # Batch embed all collected nodes
    if to_embed and HAS_VEC:
        batch_results = embed_batch(db, to_embed)
        results["embedded"] = batch_results["embedded"]
        results["errors"].extend(batch_results["errors"])

    return results


def migrate_vault_layout() -> dict:
    """Move legacy root category markdown files into the deck-style vault layout and update DB paths."""
    ensure_vault_structure()
    db = get_db()
    results = {"copied": 0, "archived": 0, "updated": 0, "skipped": 0, "errors": []}
    structured_roots = {p.split("/")[0] for p in VAULT_DIRS} | {"_meta"}
    reserved_files = {"AGENTS.md", "README.md", "index.md", "log.md"}

    for category_dir in BRAIN_DIR.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith(".") or category_dir.name in structured_roots:
            continue
        node_type = category_dir.name
        for md_file in category_dir.glob("*.md"):
            try:
                if md_file.name in reserved_files:
                    results["skipped"] += 1
                    continue
                destination_dir = ensure_category_dir(node_type)
                destination = destination_dir / md_file.name
                if not destination.exists():
                    destination.write_text(md_file.read_text(encoding="utf-8"), encoding="utf-8")
                    results["copied"] += 1
                else:
                    results["skipped"] += 1

                content = destination.read_text(encoding="utf-8")
                name_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                name = name_match.group(1).strip() if name_match else destination.stem
                nid = node_id(node_type, name)
                rel_path = str(destination.relative_to(BRAIN_DIR))
                now = datetime.now().isoformat()
                existing = db.execute("SELECT id FROM nodes WHERE id = ?", (nid,)).fetchone()
                if existing:
                    db.execute("UPDATE nodes SET file_path = ?, updated_at = ? WHERE id = ?", (rel_path, now, nid))
                else:
                    db.execute(
                        "INSERT INTO nodes (id, type, name, file_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (nid, slugify(node_type), name, rel_path, now, now)
                    )
                update_index_entry(node_type, name, rel_path)
                archive_dir = BRAIN_DIR / "50-Archive" / "legacy" / node_type
                archive_dir.mkdir(parents=True, exist_ok=True)
                archive_path = archive_dir / md_file.name
                if not archive_path.exists():
                    md_file.replace(archive_path)
                    results["archived"] += 1
                else:
                    results["skipped"] += 1
                results["updated"] += 1
            except Exception as e:
                results["errors"].append(f"{md_file}: {e}")

    db.commit()
    append_vault_log("Migrated", "vault-layout", ".")
    return results

# --- CLI ---

if __name__ == "__main__":
    # Handle --brain <path> flag
    args = sys.argv[1:]
    if "--brain" in args:
        idx = args.index("--brain")
        BRAIN_DIR = Path(args[idx + 1]).expanduser()
        DB_PATH = BRAIN_DIR / ".graph.db"
        args = args[:idx] + args[idx+2:]

    if len(args) < 1:
        print(json.dumps({"error": "Commands: init, add, edge, log, search, fts, vec, neighbors, read, query, types, list, delete, reindex, rebuild, migrate-vault, stats"}))
        sys.exit(1)

    # Ensure brain dir exists
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)

    cmd = args[0]
    try:
        if cmd == "init":
            result = init_vault()
        elif cmd == "add":
            result = add_node(args[1], args[2], args[3] if len(args) > 3 else "")
        elif cmd == "edge":
            result = add_edge(args[1], args[2], args[3], args[4], args[5])
        elif cmd == "log":
            result = log_event(args[1], args[2], args[3])
        elif cmd == "search":
            node_type = args[2] if len(args) > 2 else None
            result = search(args[1], node_type)
        elif cmd == "fts":
            result = fts_search(args[1])
        elif cmd == "vec":
            result = vec_search(args[1])
        elif cmd == "neighbors":
            hops = int(args[2]) if len(args) > 2 else 1
            result = get_neighbors(args[1], hops)
        elif cmd == "read":
            result = read_node_content(args[1])
        elif cmd == "query":
            hops = int(args[2]) if len(args) > 2 else 2
            result = query_related(args[1], hops)
        elif cmd == "types":
            result = list_types()
        elif cmd == "list":
            node_type = args[1] if len(args) > 1 else None
            result = list_nodes(node_type)
        elif cmd == "delete":
            result = delete_node(args[1])
        elif cmd == "rebuild":
            result = rebuild()
        elif cmd == "migrate-vault":
            result = migrate_vault_layout()
        elif cmd == "reindex":
            force = "--force" in args
            result = reindex_all(force=force)
        elif cmd == "stats":
            result = stats()
        else:
            result = {"error": f"Unknown command: {cmd}"}

        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
