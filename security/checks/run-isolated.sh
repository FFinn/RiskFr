#!/usr/bin/env bash
# Создаёт только временные учебные контейнеры; внешняя база не используется.
set -euo pipefail
assessment_root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
assessment_tmp=$(mktemp -d)
assessment_name="riskfr-check-$$"
cleanup() {
  docker rm -fv "${assessment_name}-db" "${assessment_name}-redis" >/dev/null 2>&1 || true
  docker network rm "$assessment_name" >/dev/null 2>&1 || true
  rm -f "$assessment_tmp/isolated.env"
  rmdir "$assessment_tmp"
}
trap cleanup EXIT
umask 077
assessment_password=$(openssl rand -hex 24)
cat > "$assessment_tmp/isolated.env" <<EOF
POSTGRES_PASSWORD=$assessment_password
POSTGRES_USER=auditor
POSTGRES_DB=riskfr_audit
POSTGRES_DSN=postgresql://auditor:$assessment_password@riskfr-audit-db:5432/riskfr_audit
REDIS_URL=redis://riskfr-audit-redis:6379/0
RISKFR_ISOLATED=YES
EOF
docker build -f "$assessment_root/security/checks/Dockerfile" -t riskfr-assessment "$assessment_root"
docker network create --internal "$assessment_name" >/dev/null
docker run -d --name "${assessment_name}-db" --network "$assessment_name" \
  --network-alias riskfr-audit-db --env-file "$assessment_tmp/isolated.env" \
  postgres:16@sha256:f9a7b9ebf6f56201f949db745e47bc423c0f0f8294bafe991cc10bf74b029657 >/dev/null
docker run -d --name "${assessment_name}-redis" --network "$assessment_name" \
  --network-alias riskfr-audit-redis \
  redis:7@sha256:2e3eb11462c4e3759e6972678dd051d150ff54b1e60714b3c33b701260172a90 >/dev/null
assessment_ready=0
for attempt in $(seq 1 30); do
  if docker exec "${assessment_name}-db" pg_isready -U auditor -d riskfr_audit >/dev/null 2>&1; then
    assessment_ready=1
    break
  fi
  sleep 1
done
test "$assessment_ready" = 1
docker run --rm --network "$assessment_name" --env-file "$assessment_tmp/isolated.env" \
  -v "$assessment_root:/assessment:ro" riskfr-assessment > "$assessment_root/security/reports/behaviour.json"
printf 'Результат: security/reports/behaviour.json\n'
