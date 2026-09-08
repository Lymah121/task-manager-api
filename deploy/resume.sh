#!/usr/bin/env bash
# Bring the paused stack back up.
#
# RDS takes several minutes to become available; EC2 is up in under a minute.
# The containers restart themselves on boot (systemd unit + docker
# `--restart unless-stopped`), and the app's entrypoint re-applies migrations,
# so no manual deploy step is needed.
set -euo pipefail

REGION=us-east-1

echo "== RDS (slowest, so start it first) =="
STATUS=$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier taskmanager-db \
  --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo missing)
case "$STATUS" in
  stopped)
    aws rds start-db-instance --region "$REGION" --db-instance-identifier taskmanager-db \
      --query 'DBInstance.DBInstanceStatus' --output text
    ;;
  available|starting) echo "  already $STATUS" ;;
  *)                  echo "  status is '$STATUS'" ;;
esac

echo "== EC2 =="
IID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=taskmanager-api" "Name=instance-state-name,Values=stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IID" ]; then
  aws ec2 start-instances --region "$REGION" --instance-ids $IID \
    --query 'StartingInstances[].{Id:InstanceId,To:CurrentState.Name}' --output table
  aws ec2 wait instance-running --region "$REGION" --instance-ids $IID
  echo "  instance running"
else
  echo "  no stopped instance (already running?)"
fi

EIP=$(aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=tag:Name,Values=taskmanager-eip" \
  --query 'Addresses[0].PublicIp' --output text 2>/dev/null || echo "")

echo
echo "Waiting for the API to answer (RDS may still be starting)..."
for i in $(seq 1 60); do
  CODE=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://${EIP}/health" 2>/dev/null || echo 000)
  if [ "$CODE" = "200" ]; then
    echo "  live: http://${EIP}/health"
    exit 0
  fi
  sleep 10
done

echo "  not answering yet. RDS can take ~5 minutes; check with:"
echo "    aws rds describe-db-instances --db-instance-identifier taskmanager-db \\"
echo "      --query 'DBInstances[0].DBInstanceStatus' --output text"
echo "    aws ssm start-session --target <instance-id>"
