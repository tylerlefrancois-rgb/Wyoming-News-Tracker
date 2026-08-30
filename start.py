import os
import threading
from http.server import ThreadingHTTPServer

from server import Handler


assigned_port = int(os.environ.get("PORT", "8080"))
candidates = [assigned_port, 8501, 8080, 8000, 5000, 3000]
ports = []
for candidate in candidates:
    if candidate not in ports:
        ports.append(candidate)

servers = []
for port in ports:
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        servers.append((port, server))
    except OSError as exc:
        print(f"Skipping unavailable port {port}: {exc}", flush=True)

if not servers:
    raise RuntimeError("No HTTP ports could be opened")

for port, server in servers[1:]:
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"http-{port}",
        daemon=True,
    )
    thread.start()
    print(f"Wyoming Policy News Tracker listening on compatibility port {port}", flush=True)

primary_port, primary_server = servers[0]
print(f"Wyoming Policy News Tracker listening on primary port {primary_port}", flush=True)
primary_server.serve_forever()
