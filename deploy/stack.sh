#!/bin/bash
# Deploy both services behind Caddy on a single host.
#
#   Internet ──443──> Caddy ──> task-manager-api:8000   (tasks domain)
#                          └──> ecommerce-api:8000      (shop domain)
#
# The application containers publish NO host ports. They are reachable only on
# the internal Docker network, by container name, so the only thing listening on
# a public interface is Caddy. That is a real reduction in attack surface, not
# just tidiness: a misconfigured security group cannot expose uvicorn directly.
#
# Domains are read from SSM so this script carries no environment-specific
# values and can be re-run unchanged by SSM Run Command from CI.
#
#   ./stack.sh                 # deploy both at :latest
#   ./stack.sh task-manager-api <tag>
set -euo pipefail

REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
NETWORK=edge

ONLY_SERVICE="${1:-}"
IMAGE_TAG="${2:-latest}"

log() { echo "[stack] $*"; }

param() {
  aws ssm get-parameter --name "$1" --with-decryption \
    --query Parameter.Value --output text --region "$REGION" 2>/dev/null || echo ""
}

TASKS_DOMAIN=$(param /stack/tasks_domain)
SHOP_DOMAIN=$(param /stack/shop_domain)
ACME_EMAIL=$(param /stack/acme_email)

if [ -z "$TASKS_DOMAIN" ] || [ -z "$SHOP_DOMAIN" ]; then
  log "ERROR: /stack/tasks_domain and /stack/shop_domain must be set in SSM"
  exit 1
fi

log "resolving database endpoint"
DB_HOST=""
for _ in $(seq 1 30); do
  DB_HOST=$(aws rds describe-db-instances --db-instance-identifier taskmanager-db \
    --query 'DBInstances[0].Endpoint.Address' --output text --region "$REGION" 2>/dev/null || true)
  [ -n "$DB_HOST" ] && [ "$DB_HOST" != "None" ] && break
  sleep 10
done
[ -n "$DB_HOST" ] && [ "$DB_HOST" != "None" ] || { log "database unavailable"; exit 1; }

DB_PASSWORD=$(param /taskmanager/db_password)
TASKS_JWT=$(param /taskmanager/jwt_secret)
SHOP_JWT=$(param /ecommerce/jwt_secret)

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

deploy_app() {
  local name="$1" database="$2" jwt="$3"
  log "deploying ${name}:${IMAGE_TAG}"
  docker pull "${REGISTRY}/${name}:${IMAGE_TAG}"
  docker rm -f "$name" >/dev/null 2>&1 || true
  # No -p: reachable only from the edge network. The entrypoint applies
  # migrations before uvicorn starts, so a fresh container converges the schema.
  docker run -d \
    --name "$name" \
    --network "$NETWORK" \
    --restart unless-stopped \
    --log-driver awslogs \
    --log-opt awslogs-region="$REGION" \
    --log-opt awslogs-group="/ship-week/${name}" \
    --log-opt awslogs-create-group=true \
    --log-opt awslogs-stream="$(hostname)" \
    -e DATABASE_URL="postgresql+psycopg://appadmin:${DB_PASSWORD}@${DB_HOST}:5432/${database}" \
    -e JWT_SECRET="$jwt" \
    "${REGISTRY}/${name}:${IMAGE_TAG}"
}

if [ -z "$ONLY_SERVICE" ] || [ "$ONLY_SERVICE" = "task-manager-api" ]; then
  deploy_app task-manager-api taskmanager "$TASKS_JWT"
fi
if [ -z "$ONLY_SERVICE" ] || [ "$ONLY_SERVICE" = "ecommerce-api" ]; then
  deploy_app ecommerce-api ecommerce "$SHOP_JWT"
fi

log "writing Caddyfile"
install -d -m 0755 /opt/stack
cat > /opt/stack/Caddyfile <<CADDY
{
$( [ -n "$ACME_EMAIL" ] && echo "  email ${ACME_EMAIL}" )
}

${TASKS_DOMAIN} {
  reverse_proxy task-manager-api:8000
  encode gzip
  header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options nosniff
    X-Frame-Options DENY
    -Server
  }
}

${SHOP_DOMAIN} {
  reverse_proxy ecommerce-api:8000
  encode gzip
  header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains"
    X-Content-Type-Options nosniff
    X-Frame-Options DENY
    -Server
  }
}
CADDY

log "starting Caddy"
docker rm -f caddy >/dev/null 2>&1 || true
# Named volumes for certificates: Let's Encrypt rate-limits issuance, so losing
# them on every restart would eventually lock us out for a week.
docker run -d \
  --name caddy \
  --network "$NETWORK" \
  --restart unless-stopped \
  -p 80:80 -p 443:443 \
  -v /opt/stack/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:2-alpine

docker image prune -f >/dev/null 2>&1 || true
log "deployed. tasks=https://${TASKS_DOMAIN}  shop=https://${SHOP_DOMAIN}"
