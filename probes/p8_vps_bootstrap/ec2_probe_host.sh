#!/usr/bin/env bash
# A throwaway EC2 host for probe P8, in the PERSONAL account only: the account guard runs first
# and refuses anything else, with no override. Not a hosting decision (D14 forbids continuous AWS
# compute); the instance self-terminates after two hours by a shutdown timer in its user-data and
# terminate-on-shutdown, so a dead session cannot leave it running.
#
#   ec2_probe_host.sh up       create key pair, security group (SSH from this machine only), instance
#   ec2_probe_host.sh status   instance id, state, public IP
#   ec2_probe_host.sh down     terminate, then delete the security group and key pair
#
# `up` is re-entrant: a security group or key pair left by an earlier partial run is reused.
set -euo pipefail
# Git Bash on Windows rewrites arguments that start with / into C:\... paths; the SSM parameter
# names below must reach the CLI untouched. Harmless on a real Linux shell.
export MSYS_NO_PATHCONV=1
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../infra/guard.sh
. "$here/../../infra/guard.sh"

REGION="${REGION:-eu-west-1}"
NAME="ephemera-p8-probe"
KEY="${KEY:-$HOME/.ssh/ephemera_ed25519}"
TYPE="${TYPE:-t3.small}"

find_instances() {
  aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text
}

find_sg() {
  aws ec2 describe-security-groups --region "$REGION" --filters "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true
}

case "${1:?up|status|down}" in
  up)
    if [ -n "$(find_instances)" ]; then echo "already up: $(find_instances)" >&2; exit 1; fi
    myip="$(curl -s --max-time 10 https://checkip.amazonaws.com)"
    vpc="$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
    sg="$(find_sg)"
    if [ -z "$sg" ] || [ "$sg" = "None" ]; then
      sg="$(aws ec2 create-security-group --region "$REGION" --group-name "$NAME" --vpc-id "$vpc" \
            --description "P8 probe: SSH from the owner address only" --query GroupId --output text)"
      aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$sg" --protocol tcp --port 22 --cidr "$myip/32" >/dev/null
    fi
    if ! aws ec2 describe-key-pairs --region "$REGION" --key-names "$NAME" >/dev/null 2>&1; then
      # The Windows CLI cannot read a Git Bash /c/... path; hand it a native path when cygpath exists.
      pub="$KEY.pub"; command -v cygpath >/dev/null && pub="$(cygpath -w "$pub")"
      aws ec2 import-key-pair --region "$REGION" --key-name "$NAME" --public-key-material "fileb://$pub" >/dev/null
    fi
    ami="$(aws ssm get-parameter --region "$REGION" --query Parameter.Value --output text \
           --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id)"
    userdata='#!/bin/bash
shutdown -h +120
apt-get update -qq
apt-get install -y -qq python3-venv git curl >/dev/null'
    iid="$(aws ec2 run-instances --region "$REGION" --image-id "$ami" --instance-type "$TYPE" \
           --key-name "$NAME" --security-group-ids "$sg" \
           --instance-initiated-shutdown-behavior terminate \
           --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":16,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
           --user-data "$userdata" \
           --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=project,Value=ephemera},{Key=purpose,Value=p8-probe}]" \
           --query 'Instances[0].InstanceId' --output text)"
    aws ec2 wait instance-running --region "$REGION" --instance-ids "$iid"
    ip="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$iid" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
    echo "up: $iid $ip (ssh from $myip only; self-terminates in 120 min)"
    ;;
  status)
    aws ec2 describe-instances --region "$REGION" --filters "Name=tag:Name,Values=$NAME" \
      --query 'Reservations[].Instances[].[InstanceId,State.Name,PublicIpAddress,LaunchTime]' --output text
    ;;
  down)
    ids="$(find_instances)"
    if [ -n "$ids" ]; then
      # shellcheck disable=SC2086
      aws ec2 terminate-instances --region "$REGION" --instance-ids $ids >/dev/null
      # shellcheck disable=SC2086
      aws ec2 wait instance-terminated --region "$REGION" --instance-ids $ids
      echo "terminated: $ids"
    fi
    aws ec2 delete-key-pair --region "$REGION" --key-name "$NAME" 2>/dev/null && echo "key pair deleted" || true
    sg="$(find_sg)"
    if [ -n "$sg" ] && [ "$sg" != "None" ]; then
      aws ec2 delete-security-group --region "$REGION" --group-id "$sg" && echo "security group deleted"
    fi
    ;;
esac
