#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

SSH_KEY="${DIPLOM_SSH_KEY:-$HOME/.ssh/id_ed25519}"
KNOWN_HOSTS="${DIPLOM_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"

test -s ansible/inventory/diplom/hosts.yml
test -s ansible/kubespray-image.txt
test -r "$SSH_KEY"
test -r "$KNOWN_HOSTS"

mkdir -p .secrets/logs

if [ "$#" -eq 0 ]; then
  set -- cluster.yml
fi

docker run --rm --network host \
  --mount "type=bind,src=$PROJECT_DIR/ansible/inventory/diplom,dst=/inventory" \
  --mount "type=bind,src=$SSH_KEY,dst=/root/.ssh/id_ed25519,readonly" \
  --mount "type=bind,src=$KNOWN_HOSTS,dst=/root/.ssh/known_hosts,readonly" \
  -e ANSIBLE_HOST_KEY_CHECKING=True \
  -e 'ANSIBLE_SSH_ARGS=-o ControlMaster=auto -o ControlPersist=60s -o UserKnownHostsFile=/root/.ssh/known_hosts -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes' \
  "$(cat ansible/kubespray-image.txt)" \
  ansible-playbook \
    -i /inventory/hosts.yml \
    --private-key /root/.ssh/id_ed25519 \
    --become \
    "$@" \
  2>&1 | tee ".secrets/logs/kubespray-$(date +%Y%m%d-%H%M%S).log"
