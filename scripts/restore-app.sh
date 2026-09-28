#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ "$#" -ne 1 ]; then
  printf 'Использование: %s sha256:DIGEST\n' "$0" >&2
  exit 2
fi

APP_DIGEST="$1"
if [[ ! "$APP_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'Ожидался digest вида sha256: и 64 шестнадцатеричных символа\n' >&2
  exit 2
fi

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

test -s .secrets/registry-puller-key.json
id diplom-runner >/dev/null
sudo -v

unset AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE

AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap \
  output -raw state_access_key)"
AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap \
  output -raw state_secret_key)"

test -n "$AWS_ACCESS_KEY_ID"
test -n "$AWS_SECRET_ACCESS_KEY"

export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_EC2_METADATA_DISABLED=true

APP_REPOSITORY="$(terraform -chdir=terraform/infrastructure \
  output -raw app_image_repository)"

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

if [[ ! "$APP_REPOSITORY" =~ ^cr\.yandex/[a-z0-9]+/devops-diplom-app$ ]]; then
  printf 'Неожиданный адрес репозитория образов\n' >&2
  exit 1
fi

APP_IMAGE="$APP_REPOSITORY@$APP_DIGEST"
printf 'Образ для развёртывания: %s\n' "$APP_IMAGE"

APP_MANIFEST="$(kubectl set image \
  --local \
  -f kubernetes/app/deployment.yaml \
  "nginx=$APP_IMAGE" \
  -o yaml)"

# При совпадении образа set image не выводит объект.
if [ -z "$APP_MANIFEST" ]; then
  APP_MANIFEST="$(cat kubernetes/app/deployment.yaml)"
fi

test -n "$APP_MANIFEST"

kubectl --request-timeout=30s apply \
  -f kubernetes/app/namespace.yaml

python3 scripts/create-registry-pull-secret.py

printf '%s\n' "$APP_MANIFEST" |
  kubectl --request-timeout=30s apply -f -

kubectl --request-timeout=30s apply \
  -f kubernetes/app/service.yaml \
  -f kubernetes/app/ingress.yaml

kubectl --request-timeout=240s -n diplom-app \
  rollout status deployment/diplom-app --timeout=180s

CURRENT_IMAGE="$(kubectl --request-timeout=30s \
  -n diplom-app get deployment diplom-app \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="nginx")].image}')"

[[ "$CURRENT_IMAGE" == "$APP_IMAGE" ]]

# Создание ограниченного доступа CD и установка краткоживущего токена.
kubectl --request-timeout=30s apply -f kubernetes/app/deployer-rbac.yaml
bash scripts/refresh-deployer-access.sh

kubectl --request-timeout=30s -n diplom-app \
  get deployment,pods,service,ingress -o wide

printf '\nПриложение развёрнуто, доступ CD-runner обновлён\n'
