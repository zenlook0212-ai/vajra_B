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

echo "== patch Open WebUI native FC (tool_choice scope) =="
docker cp "$SCRIPT_DIR/openwebui_patch_native_fc.py" "$CONTAINER:/tmp/openwebui_patch_native_fc.py"
docker exec "$CONTAINER" python3 /tmp/openwebui_patch_native_fc.py

echo "== patch Open WebUI model toolIds auto-bind =="
docker cp "$SCRIPT_DIR/openwebui_patch_model_toolids.py" "$CONTAINER:/tmp/openwebui_patch_model_toolids.py"
docker exec "$CONTAINER" python3 /tmp/openwebui_patch_model_toolids.py

echo "== patch Open WebUI Canon scope (skip tools for chitchat) =="
docker cp "$SCRIPT_DIR/openwebui_patch_canon_scope.py" "$CONTAINER:/tmp/openwebui_patch_canon_scope.py"
docker exec "$CONTAINER" python3 /tmp/openwebui_patch_canon_scope.py

echo "== patch Open WebUI Canon RAG passthrough (skip LLM round 2) =="
docker cp "$SCRIPT_DIR/openwebui_patch_canon_passthrough.py" "$CONTAINER:/tmp/openwebui_patch_canon_passthrough.py"
docker exec "$CONTAINER" python3 /tmp/openwebui_patch_canon_passthrough.py

echo "== configure qwen35b + qwen35b-thinking =="
docker cp "$SCRIPT_DIR/openwebui_configure_qwen.py" "$CONTAINER:/tmp/openwebui_configure_qwen.py"
docker exec "$CONTAINER" python3 /tmp/openwebui_configure_qwen.py

echo "== smoke from container =="
docker exec "$CONTAINER" curl -sf -m 30 "${GATEWAY_URL}/v1/modes" | head -c 120
echo
echo "OK — qwen35b (Canon RAG, thinking off) + qwen35b-thinking (thinking on)."
