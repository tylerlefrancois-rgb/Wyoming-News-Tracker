import os
import threading
from http.server import ThreadingHTTPServer

from server import Handler


assigned_port = int(os.environ.get("PORT", "8080"))
ports = []
for candidate in (assigned_port, 8501):
    if candidate not in ports:
        ports.append(candidate)

servers = []
for port in ports:
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    servers.append((port, server))

for port, server in servers[1:]:
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"http-{port}",
        daemon=True,
    )
    thread.start()
    print(f"Wyoming Policy News Tracker listening on legacy port {port}", flush=True)

primary_port, primary_server = servers[0]
print(f"Wyoming Policy News Tracker listening on Railway port {primary_port}", flush=True)
primary_server.serve_forever()
