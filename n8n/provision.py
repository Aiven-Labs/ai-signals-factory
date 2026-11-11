"""Create the Telegram credential and import the workflows into n8n through its public API.
Secrets are read from files and never printed.
  python3 n8n/provision.py https://<n8n-host> ~/n8n-api.txt ~/telegram_token.txt"""
import json, sys, urllib.request, pathlib

base, key_file, tok_file = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
key = pathlib.Path(key_file).expanduser().read_text().strip()
tok = pathlib.Path(tok_file).expanduser().read_text().strip()


def call(method, path, body=None):
    req = urllib.request.Request(base + "/api/v1" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, path, e.read()[:300].decode(errors="replace").replace(tok, "***"))
        raise SystemExit(1)


existing = {c.get("name"): c for c in call("GET", "/credentials?limit=100").get("data", [])} if False else {}
cred = call("POST", "/credentials", {"name": "AI Signals bot", "type": "telegramApi",
                                     "data": {"accessToken": tok, "baseUrl": "https://api.telegram.org"}})
print("credential id:", cred["id"])
here = pathlib.Path(__file__).parent / "workflows"
for name in ("telegram-outbox.json", "telegram-decisions.json"):
    wf = json.loads((here / name).read_text().replace("__CRED_ID__", cred["id"]))
    made = call("POST", "/workflows", {"name": wf["name"], "nodes": wf["nodes"], "connections": wf["connections"],
                                       "settings": {"executionOrder": "v1"}})
    act = call("POST", f"/workflows/{made['id']}/activate")
    print(wf["name"], made["id"], "active:", act.get("active"))
