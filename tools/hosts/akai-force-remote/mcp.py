#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Calls one tool of the MPC Remote addin's MCP endpoint and prints the result.

  tools/hosts/akai-force-remote/mcp.py [--url URL] [-o IMAGE.png] TOOL ['{"json": "args"}']
  tools/hosts/akai-force-remote/mcp.py --list

Needs the tunnel (install.sh tunnel). Text goes to stdout; an image in the result (a
screenshot) is saved to -o, by default out/mpc-screen.png. Stdlib only, so it works without
adding the server to an MCP client. Tool list and arguments: --list.
"""

import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path

DEFAULT_IMAGE = Path(__file__).resolve().parents[3] / "out" / "mpc-screen.png"


class Session:
    def __init__(self, url):
        self.url, self.sid, self.next_id = url, None, 1

    def post(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            msg["id"] = self.next_id
            self.next_id += 1
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, json.dumps(msg).encode(), headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            self.sid = r.headers.get("Mcp-Session-Id", self.sid)
            body = r.read().decode()
            kind = r.headers.get("Content-Type", "")
        if notify or not body.strip():
            return None
        if "text/event-stream" in kind:
            body = "\n".join(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
        reply = json.loads(body)
        if "error" in reply:
            sys.exit(f"mcp: {method}: {reply['error'].get('message', reply['error'])}")
        return reply["result"]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default="http://localhost:6720/mcp")
    p.add_argument("-o", "--image", type=Path, default=DEFAULT_IMAGE)
    p.add_argument("--list", action="store_true", help="list the tools")
    p.add_argument("tool", nargs="?")
    p.add_argument("args", nargs="?", default="{}")
    a = p.parse_args()
    s = Session(a.url)
    s.post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "rpi-audio", "version": "1"}})
    s.post("notifications/initialized", notify=True)
    if a.list or not a.tool:
        for t in s.post("tools/list")["tools"]:
            props = ", ".join(t.get("inputSchema", {}).get("properties", {}))
            print(f"{t['name']}({props})")
        return
    result = s.post("tools/call", {"name": a.tool, "arguments": json.loads(a.args)})
    for c in result.get("content", []):
        if c.get("type") == "text":
            print(c["text"])
        elif c.get("type") == "image":
            a.image.parent.mkdir(parents=True, exist_ok=True)
            a.image.write_bytes(base64.b64decode(c["data"]))
            print(f"[image saved to {a.image}]")
    sys.exit(1 if result.get("isError") else 0)


if __name__ == "__main__":
    main()
