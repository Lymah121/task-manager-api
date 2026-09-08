#!/usr/bin/env bash
# Stop the billable compute overnight, keeping all state and configuration.
#
# Stops:  EC2 instance hours, RDS instance hours   (~$0.68/day saved)
# Keeps:  EBS + RDS storage, Elastic IP            (~$0.22/day, unavoidable
#         while the resources exist -- AWS bills every public IPv4 address
#         since Feb 2024, attached or not, running or not)
#
# Nothing is destroyed. `resume.sh` brings it all back, and the Elastic IP stays
# associated across a stop/start, so the address does not change.
#
# NOTE: a stopped RDS instance is auto-started by AWS after 7 days. Fine for an
# overnight pause; use teardown.sh if you are done for longer than that.
set -euo pipefail

REGION=us-east-1

echo "== EC2 =="
IID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=taskmanager-api" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$IID" ]; then
  aws ec2 stop-instances --region "$REGION" --instance-ids $IID \
    --query 'StoppingInstances[].{Id:InstanceId,From:PreviousState.Name,To:CurrentState.Name}' --output table
else
  echo "  no running instance"
fi

echo "== RDS =="
STATUS=$(aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier taskmanager-db \
  --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo "missing")
case "$STATUS" in
  available)
    aws rds stop-db-instance --region "$REGION" --db-instance-identifier taskmanager-db \
      --query 'DBInstance.{Id:DBInstanceIdentifier,Status:DBInstanceStatus}' --output table
    ;;
  stopped|stopping) echo "  already $STATUS" ;;
  missing)          echo "  no such instance" ;;
  *)                echo "  status is '$STATUS'; RDS can only be stopped from 'available'" ;;
esac

echo
echo "Paused. Still billing while the resources exist:"
echo "  Elastic IP     ~\$0.12/day"
echo "  RDS storage    ~\$0.08/day"
echo "  EBS root       ~\$0.02/day"
echo "  ------------------------"
echo "  ~\$0.22/day, down from ~\$0.90/day"
echo
echo "Tomorrow:  ./deploy/resume.sh"
