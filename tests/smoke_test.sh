#!/bin/bash
# Docker smoke tests — verifies the container builds, starts, and serves correctly.
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-subtitle-pruner:test}"
CONTAINER_NAME="subtitle-pruner-smoke-test"
PORT="${PORT:-14000}"

echo "=== Starting smoke tests ==="
echo "Image: $IMAGE_NAME"

# Remove any leftover container from a previous run
docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true

# Start container
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "$PORT:14000" \
  -e LOG_LEVEL=DEBUG \
  -e ALLOWED_LANGUAGES=eng,dan \
  "$IMAGE_NAME"

# Wait for container to be ready (up to 30 seconds)
echo "Waiting for container to be ready..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$PORT/api/status" > /dev/null 2>&1; then
    echo "Container ready after ${i}s"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "FAIL: Container did not become ready in 30 seconds"
    echo "--- Container logs ---"
    docker logs "$CONTAINER_NAME"
    docker rm -f "$CONTAINER_NAME" > /dev/null
    exit 1
  fi
  sleep 1
done

FAILURES=0

run_test() {
  local description="$1"
  local result="$2"  # "PASS" or "FAIL"
  local detail="${3:-}"

  if [ "$result" = "PASS" ]; then
    echo "  PASS: $description"
  else
    echo "  FAIL: $description ${detail:+($detail)}"
    FAILURES=$((FAILURES + 1))
  fi
}

# Test 1: Web UI serves HTML with 200
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/")
if [ "$STATUS" = "200" ]; then
  run_test "Web UI returns 200" "PASS"
else
  run_test "Web UI returns 200" "FAIL" "got $STATUS"
fi

# Test 2: Web UI contains expected content
BODY=$(curl -s "http://localhost:$PORT/")
if echo "$BODY" | grep -q "Subtitle Pruner"; then
  run_test "Web UI contains 'Subtitle Pruner'" "PASS"
else
  run_test "Web UI contains 'Subtitle Pruner'" "FAIL"
fi

# Test 3: API status endpoint returns JSON with expected fields
STATUS_JSON=$(curl -s "http://localhost:$PORT/api/status")
if echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'counts' in d; assert 'worker_running' in d" 2>/dev/null; then
  run_test "/api/status returns valid JSON with counts" "PASS"
else
  run_test "/api/status returns valid JSON with counts" "FAIL"
fi

# Test 3b: Worker threads are actually running
if echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['worker_running'] is True" 2>/dev/null; then
  run_test "Worker threads are running" "PASS"
else
  run_test "Worker threads are running" "FAIL"
fi

# Test 4: Webhook accepts test event
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://localhost:$PORT/webhook" \
  -H "Content-Type: application/json" \
  -d '{"eventType": "Test", "instanceName": "Radarr"}')
if [ "$HTTP_CODE" = "200" ]; then
  run_test "Webhook accepts test event (200)" "PASS"
else
  run_test "Webhook accepts test event (200)" "FAIL" "got $HTTP_CODE"
fi

# Test 5: Webhook queues MKV file
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://localhost:$PORT/webhook" \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/media/test.mkv"}')
if [ "$HTTP_CODE" = "202" ]; then
  run_test "Webhook queues MKV file (202)" "PASS"
else
  run_test "Webhook queues MKV file (202)" "FAIL" "got $HTTP_CODE"
fi

# Test 6: Webhook rejects non-MKV
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://localhost:$PORT/webhook" \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/media/test.mp4"}')
if [ "$HTTP_CODE" = "200" ]; then
  run_test "Webhook ignores non-MKV file (200)" "PASS"
else
  run_test "Webhook ignores non-MKV file (200)" "FAIL" "got $HTTP_CODE"
fi

# Test 7: Clear history endpoint
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "http://localhost:$PORT/api/queue")
if [ "$HTTP_CODE" = "200" ]; then
  run_test "DELETE /api/queue returns 200" "PASS"
else
  run_test "DELETE /api/queue returns 200" "FAIL" "got $HTTP_CODE"
fi

# Cleanup
echo ""
echo "--- Container logs ---"
docker logs "$CONTAINER_NAME" 2>&1 | tail -20
docker rm -f "$CONTAINER_NAME" > /dev/null

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "=== All smoke tests passed ==="
  exit 0
else
  echo "=== $FAILURES smoke test(s) FAILED ==="
  exit 1
fi
