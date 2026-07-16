#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${RADIOFLOW_SPORTS_DIR:-/opt/radioflow-sports}"
IMAGE="${RADIOFLOW_SPORTS_IMAGE:-radioflow-sports-publisher:latest}"
NETWORK="${RADIOFLOW_DOCKER_NETWORK:-radioflow_default}"
COUNTRY="${RADIOFLOW_SPORTS_COUNTRY:-Chile}"
ENV_FILE="${RADIOFLOW_SPORTS_ENV_FILE:-${APP_DIR}/publisher.env}"
CONFIG_FILE="${RADIOFLOW_SPORTS_CONFIG_FILE:-${APP_DIR}/config.json}"
LOCK_FILE="${RADIOFLOW_SPORTS_LOCK_FILE:-/run/lock/radioflow-sports-publisher.lock}"

for required_command in docker flock; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "Required command is not installed: $required_command" >&2
    exit 1
  fi
done

for required_file in "$ENV_FILE" "$CONFIG_FILE"; do
  if [[ ! -r "$required_file" ]]; then
    echo "Required file is missing or unreadable: $required_file" >&2
    exit 1
  fi
done

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "RadioFlow sports publisher is already running; skipping this execution."
  exit 0
fi

docker_args=(
  run
  --rm
  --env-file "$ENV_FILE"
  --mount "type=bind,src=${CONFIG_FILE},dst=/app/config.json,readonly"
  --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=16m
  --cap-drop ALL
  --security-opt no-new-privileges
  --memory 192m
  --cpus 0.50
)

if [[ -n "$NETWORK" ]]; then
  docker_args+=(--network "$NETWORK")
fi

docker "${docker_args[@]}" "$IMAGE" --country "$COUNTRY"
