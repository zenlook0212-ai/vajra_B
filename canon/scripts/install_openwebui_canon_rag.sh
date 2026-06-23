#!/usr/bin/env bash
# Install CBETA Canon RAG tool into Open WebUI (Docker).
set -euo pipefail

CONTAINER="${OPEN_WEBUI_CONTAINER:-open-webui}"
GATEWAY_URL="${VAJRA_GATEWAY_URL:-http://host.docker.internal:8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "ERROR: container $CONTAINER not running" >&2
  exit 1
fi

echo "== ensure VAJRA_GATEWAY_URL in Open WebUI =="
COMPOSE="${OPEN_WEBUI_COMPOSE:-/home/zenlook/open-webui-docker-compose.yml}"
if [ -f "$COMPOSE" ]; then
  docker compose -f "$COMPOSE" up -d
fi

echo "== install tool cbeta_canon_rag =="
docker cp "$SCRIPT_DIR/openwebui_canon_rag.py" "$CONTAINER:/tmp/openwebui_canon_rag.py"
docker cp "$SCRIPT_DIR/openwebui_install_tool.py" "$CONTAINER:/tmp/openwebui_install_tool.py"
docker exec -e VAJRA_GATEWAY_URL="$GATEWAY_URL" "$CONTAINER" python3 /tmp/openwebui_install_tool.py

echo "== smoke from container =="
docker exec "$CONTAINER" curl -sf -m 30 "${GATEWAY_URL}/v1/modes" | head -c 120
echo
echo "OK — enable tool 'CBETA Canon RAG' in Open WebUI chat model settings."
