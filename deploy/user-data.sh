#!/bin/bash
# EC2 user-data for the Task Manager API host (Amazon Linux 2023).
#
# Secrets are NOT in this file. Anything written here is readable forever via
# the instance metadata service by any process on the box, so the credentials
# are fetched at boot from SSM Parameter Store using the instance role instead.
set -euxo pipefail

dnf update -y
dnf install -y docker
systemctl enable --now docker

install -d -m 0755 /opt/taskmanager

cat > /opt/taskmanager/run.sh <<'RUNSH'
#!/bin/bash
set -euo pipefail

REGION=us-east-1
# Derived, not hardcoded: keeps the AWS account ID out of a public repo.
ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
REPO="${REGISTRY}/task-manager-api"
IMAGE_TAG="${1:-latest}"

log() { echo "[taskmanager] $*"; }

# RDS may still be provisioning on first boot; wait rather than crash-loop.
log "resolving database endpoint"
for _ in $(seq 1 60); do
  DB_HOST=$(aws rds describe-db-instances \
    --db-instance-identifier taskmanager-db \
    --query 'DBInstances[0].Endpoint.Address' \
    --output text --region "$REGION" 2>/dev/null || true)
  [ -n "${DB_HOST:-}" ] && [ "$DB_HOST" != "None" ] && break
  log "database not ready yet, waiting"
  sleep 20
done
[ -n "${DB_HOST:-}" ] && [ "$DB_HOST" != "None" ] || { log "database never became available"; exit 1; }
log "database endpoint: $DB_HOST"

DB_PASSWORD=$(aws ssm get-parameter --name /taskmanager/db_password \
  --with-decryption --query Parameter.Value --output text --region "$REGION")
JWT_SECRET=$(aws ssm get-parameter --name /taskmanager/jwt_secret \
  --with-decryption --query Parameter.Value --output text --region "$REGION")

log "authenticating to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

log "pulling ${REPO}:${IMAGE_TAG}"
docker pull "${REPO}:${IMAGE_TAG}"

log "restarting container"
docker rm -f taskmanager-api >/dev/null 2>&1 || true

# Port 80 -> 8000. TLS via Caddy lands on Day 4.
# The image entrypoint applies Alembic migrations before uvicorn starts.
docker run -d \
  --name taskmanager-api \
  --restart unless-stopped \
  -p 80:8000 \
  -e DATABASE_URL="postgresql+psycopg://appadmin:${DB_PASSWORD}@${DB_HOST}:5432/taskmanager" \
  -e JWT_SECRET="${JWT_SECRET}" \
  -e ACCESS_TOKEN_EXPIRE_MINUTES=60 \
  "${REPO}:${IMAGE_TAG}"

log "started"
docker image prune -f >/dev/null 2>&1 || true
RUNSH

chmod 0750 /opt/taskmanager/run.sh

cat > /etc/systemd/system/taskmanager.service <<'UNIT'
[Unit]
Description=Task Manager API container
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/taskmanager/run.sh
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now taskmanager.service
