#!/usr/bin/env bash
set -u

section() {
  printf '\n===== %s =====\n' "$1"
}

section "Host"
hostnamectl 2>/dev/null || true
printf 'User: %s\n' "$(id)"
printf 'Date: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"

section "Listening TCP ports"
sudo ss -lntp 2>/dev/null || ss -lntp 2>/dev/null || true

section "RadioFlow / Node processes"
ps -ef | grep -E '[r]adioflow|[n]ext|[n]ode|[p]npm|[n]pm|[p]m2' || true

section "Relevant running services"
systemctl --no-pager --type=service --state=running 2>/dev/null \
  | grep -Ei 'radioflow|node|next|pm2|nginx|caddy|apache|docker' || true

section "Docker containers"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Networks}}' 2>/dev/null || true

section "Docker networks"
docker network ls 2>/dev/null || true

section "PostgreSQL mounts and port bindings"
postgres_container="$(docker ps -q \
  --filter label=com.docker.compose.project=radioflow \
  --filter label=com.docker.compose.service=postgres \
  | head -n 1)"
if [[ -n "$postgres_container" ]]; then
  docker inspect "$postgres_container" \
    --format 'Mounts:{{println}}{{range .Mounts}}- {{.Type}} {{.Name}} {{.Source}} -> {{.Destination}}{{println}}{{end}}PortBindings: {{json .HostConfig.PortBindings}}' \
    2>/dev/null || true
else
  echo "RadioFlow PostgreSQL container not found."
fi

section "Likely RadioFlow project directories"
find /opt /srv /var/www /home -maxdepth 4 -type f -name package.json 2>/dev/null \
  | grep -Ei 'radioflow|/opt/|/srv/|/var/www/' \
  | head -n 50 || true

section "Local HTTP probes"
for port in 3000 3001 8080 80 443; do
  if curl --max-time 3 --silent --show-error --output /dev/null \
    --write-out "port ${port}: HTTP %{http_code}\n" "http://127.0.0.1:${port}/" 2>/dev/null; then
    :
  else
    printf 'port %s: unavailable\n' "$port"
  fi
done

section "SSH listeners"
sudo ss -lntp 2>/dev/null | grep -E 'sshd|:22\b|:2222\b' || true

printf '\nInspection complete. This script made no changes.\n'
