"""Lightweight HTTP API for the brain. Run: python ~/.copilot/m-skills/brain/serve.py"""
import http.server
import json
import sys
import urllib.parse
from pathlib import Path

# Import brain.py from the same directory as this script
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain

PORT = 7433

class BrainHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        q = params.get("q", [""])[0]

        try:
            if path == "/stats":
                result = brain.stats()
            elif path == "/query" and q:
                result = brain.query_related(q)
            elif path == "/vec" and q:
                result = brain.vec_search(q)
            elif path == "/fts" and q:
                result = brain.fts_search(q)
            elif path == "/search" and q:
                result = brain.search(q)
            elif path == "/graph":
                db = brain.get_db()
                nodes = [dict(r) for r in db.execute("SELECT id, type, name FROM nodes").fetchall()]
                edges = [dict(r) for r in db.execute("SELECT source_id, target_id, relationship FROM edges").fetchall()]
                result = {"nodes": nodes, "edges": edges}
            elif path == "/list":
                result = brain.list_nodes(q or None)
            elif path == "/read" and q:
                result = brain.read_node_content(q)
            else:
                result = {"error": "Unknown endpoint or missing ?q= param"}

            self.send_response(200)
        except Exception as e:
            result = {"error": str(e)}
            self.send_response(500)

        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(result, indent=2, default=str).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"  {args[0]}")

if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), BrainHandler)
    print(f"Brain API running on http://localhost:{PORT}")
    print(f"Endpoints: /stats /query?q= /vec?q= /fts?q= /search?q= /list /read?q=")
    print(f"Press Ctrl+C to stop")
    server.serve_forever()
