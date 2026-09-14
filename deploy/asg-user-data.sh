#!/bin/bash
# User-data for instances launched by the auto scaling group.
#
# Deliberately NOT the same as the single-instance setup. These instances sit
# behind an Application Load Balancer, so:
#
#   * No Caddy, no ACME. TLS belongs at the load balancer in this topology, and
#     an ASG instance could not pass an HTTP-01 challenge anyway -- the domain
#     resolves to the Elastic IP, not to whichever instance the ASG just made.
#     Letting each new instance retry a doomed challenge would burn Let's
#     Encrypt rate limits for the whole domain.
#   * The app listens on port 80 directly; the ALB health-checks GET /health.
#
# Secrets come from SSM via the instance role, exactly as on the primary host.
set -euxo pipefail

dnf update -y
dnf install -y docker
systemctl enable --now docker

REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region "$REGION")
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

DB_HOST=$(aws rds describe-db-instances --db-instance-identifier taskmanager-db \
  --query 'DBInstances[0].Endpoint.Address' --output text --region "$REGION")
DB_PASSWORD=$(aws ssm get-parameter --name /taskmanager/db_password --with-decryption \
  --query Parameter.Value --output text --region "$REGION")
JWT_SECRET=$(aws ssm get-parameter --name /taskmanager/jwt_secret --with-decryption \
  --query Parameter.Value --output text --region "$REGION")

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker pull "${REGISTRY}/task-manager-api:latest"

docker run -d \
  --name task-manager-api \
  --restart unless-stopped \
  -p 80:8000 \
  --log-driver awslogs \
  --log-opt awslogs-region="$REGION" \
  --log-opt awslogs-group=/ship-week/task-manager-api \
  --log-opt awslogs-create-group=true \
  --log-opt awslogs-stream="asg-$(hostname)" \
  -e DATABASE_URL="postgresql+psycopg://appadmin:${DB_PASSWORD}@${DB_HOST}:5432/taskmanager" \
  -e JWT_SECRET="$JWT_SECRET" \
  "${REGISTRY}/task-manager-api:latest"
