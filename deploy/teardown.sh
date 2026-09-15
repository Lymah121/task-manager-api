#!/usr/bin/env bash
# Delete every billable resource created for this deployment.
#
# Run this when the demo is finished. Left running, the stack costs roughly
# $27/month; the Elastic IP is billed even while attached, and RDS keeps
# charging for storage even when the instance is stopped.
#
#   ./deploy/teardown.sh          # show what would be deleted
#   ./deploy/teardown.sh --yes    # actually delete
set -euo pipefail

REGION=us-east-1
DRY_RUN=true
[ "${1:-}" = "--yes" ] && DRY_RUN=false

run() {
  if $DRY_RUN; then
    echo "  would run: $*"
  else
    echo "  running: $*"
    "$@" || echo "  (already gone, continuing)"
  fi
}

echo "== EC2 instance =="
IID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=taskmanager-api" "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
[ -n "$IID" ] && run aws ec2 terminate-instances --region "$REGION" --instance-ids $IID || echo "  none found"

echo "== Elastic IP (billed even while attached) =="
ALLOC=$(aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=tag:Name,Values=taskmanager-eip" \
  --query 'Addresses[].AllocationId' --output text)
if [ -n "$ALLOC" ]; then
  $DRY_RUN || aws ec2 wait instance-terminated --region "$REGION" --instance-ids $IID 2>/dev/null || true
  run aws ec2 release-address --region "$REGION" --allocation-id $ALLOC
else
  echo "  none found"
fi

echo "== RDS instance =="
run aws rds delete-db-instance --region "$REGION" \
  --db-instance-identifier taskmanager-db --skip-final-snapshot --delete-automated-backups

echo "== RDS subnet group (after the instance is gone) =="
if ! $DRY_RUN; then
  aws rds wait db-instance-deleted --region "$REGION" --db-instance-identifier taskmanager-db 2>/dev/null || true
fi
run aws rds delete-db-subnet-group --region "$REGION" --db-subnet-group-name taskmanager-subnet-group

echo "== ECR repositories =="
for repo in task-manager-api ecommerce-api; do
  run aws ecr delete-repository --region "$REGION" --repository-name "$repo" --force
done

echo "== CloudWatch log groups and alarms =="
for grp in /ship-week/task-manager-api /ship-week/ecommerce-api; do
  run aws logs delete-log-group --region "$REGION" --log-group-name "$grp"
done
run aws cloudwatch delete-alarms --region "$REGION"   --alarm-names task-manager-api-5xx-rate ecommerce-api-5xx-rate

echo "== SSM parameters (free, but they hold live secrets) =="
for prm in /taskmanager/db_password /taskmanager/jwt_secret /ecommerce/jwt_secret            /stack/tasks_domain /stack/shop_domain /stack/acme_email; do
  run aws ssm delete-parameter --region "$REGION" --name "$prm"
done

echo "== Security groups (after dependents are gone) =="
for name in taskmanager-db-sg taskmanager-app-sg; do
  SG=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=$name" --query 'SecurityGroups[].GroupId' --output text 2>/dev/null || true)
  [ -n "$SG" ] && run aws ec2 delete-security-group --region "$REGION" --group-id "$SG" || echo "  $name: none found"
done

echo "== IAM role and instance profile =="
run aws iam remove-role-from-instance-profile --instance-profile-name taskmanager-ec2-profile --role-name taskmanager-ec2-role
run aws iam delete-instance-profile --instance-profile-name taskmanager-ec2-profile
run aws iam delete-role-policy --role-name taskmanager-ec2-role --policy-name read-taskmanager-parameters
for arn in arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly; do
  run aws iam detach-role-policy --role-name taskmanager-ec2-role --policy-arn "$arn"
done
run aws iam delete-role --role-name taskmanager-ec2-role

echo
echo "NOT deleted (free, and you want them if you rebuild):"
echo "  - IAM role github-actions-deploy and the GitHub OIDC provider"
echo "  - Budgets (the first two are free)"
echo
$DRY_RUN && echo "Dry run. Re-run with --yes to actually delete." || echo "Teardown complete. Check the Billing console tomorrow to confirm."
