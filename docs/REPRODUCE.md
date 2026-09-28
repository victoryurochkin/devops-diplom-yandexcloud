# Воспроизведение стенда DevOps

Инструкция относится к репозиториям Виктора Юрочкина:

- [Инфраструктура](https://github.com/victoryurochkin/devops-diplom-yandexcloud).
- [Приложение](https://github.com/victoryurochkin/devops-diplom-app).

28.09.2026 проверено удаление и повторное создание всех 10 ресурсов
`terraform/infrastructure`, установка Kubernetes, восстановление мониторинга
с историей и приложения, затем автоматический выпуск `v1.0.1`.
Bootstrap, его локальный state, сервисные аккаунты и S3-бакет сохранялись.
Установка с новым bootstrap описана ниже; его удаление в проверку не входило.

Это последовательность для оператора, а не установка всего стенда одной командой.
Terraform создаёт облачные ресурсы; Kubernetes устанавливает Kubespray,
компоненты кластера — Helm и скрипты из репозитория.
Для работающего стенда повторять раздел удаления не требуется.

## 1. Управляющий хост и исходные параметры

Нужен Linux x86_64 с Bash, Git, Docker, Python 3 с модулем venv, SSH,
curl, Terraform 1.9.8, Helm 3, Yandex Cloud CLI и GitHub CLI.
kubectl устанавливается из артефактов Kubespray в разделе 4.
При восстановлении образа из Docker-архива дополнительно используется Skopeo.
На управляющем хосте нужны sudo и доступ к Docker.
Этот же хост обслуживает CD-runner и должен быть включён при деплое.

Закреплённые версии:

| Компонент | Источник версии |
|---|---|
| Terraform | 1.9.8; `.github/workflows/terraform.yml` |
| Yandex provider | 0.230.0; `versions.tf`, `.terraform.lock.hcl` |
| Kubespray | v2.32.0, образ по digest в `ansible/kubespray-image.txt` |
| Kubernetes | 1.36.4 в проверенной установке |
| Traefik chart | `kubernetes/traefik/chart-version.txt` |
| Мониторинг chart | `kubernetes/monitoring/chart-version.txt` |
| nginx | digest в Dockerfile репозитория приложения |
| Registry SDK | `scripts/registry-tools-requirements.txt` |

Для нового окружения заранее создать облако/каталог с платёжным аккаунтом,
проверить квоты на три ВМ и публичные IP. Настроить пользовательский профиль
`yc init`. Пользователю bootstrap нужны права на создание сервисных аккаунтов,
назначение перечисленных в `terraform/bootstrap` ролей, создание ключей и бакета.
Рабочий Terraform-аккаунт получает отдельные сервисные роли из `main.tf`,
роль суперпользователя ему не назначается.

Авторизоваться в GitHub CLI:

    gh auth login --hostname github.com --git-protocol ssh --web
    gh auth status

Клонировать оба репозитория в домашний каталог. Если они уже существуют,
использовать имеющиеся рабочие копии; не клонировать поверх них.

    git clone git@github.com:victoryurochkin/devops-diplom-yandexcloud.git "$HOME/devops-diplom-yandexcloud"
    git clone git@github.com:victoryurochkin/devops-diplom-app.git "$HOME/devops-diplom-app"
    cd "$HOME/devops-diplom-yandexcloud"
    umask 077
    mkdir -p .secrets
    chmod 700 .secrets

В примерах ниже команды выполняются в Bash из корня инфраструктурного
репозитория, если другой каталог не указан. Используется существующая SSH-пара
`~/.ssh/id_ed25519` и `~/.ssh/id_ed25519.pub`. Если пары нет, создать её
через `ssh-keygen -t ed25519`; существующий ключ не перезаписывать.

Для отдельной копии проекта понадобятся собственные GitHub-репозитории
с правами записи. Заменить адреса в командах настройки GitHub и целевой
репозиторий в `scripts/sync-app-ci-vars.py`; сами workflow используют
текущий репозиторий запуска.

На новом окружении скопировать примеры, затем заполнить значения:

    cp -n terraform/bootstrap/terraform.tfvars.example terraform/bootstrap/terraform.tfvars
    cp -n terraform/infrastructure/terraform.tfvars.example terraform/infrastructure/terraform.tfvars
    cp -n terraform/infrastructure/compute.auto.tfvars.json.example terraform/infrastructure/compute.auto.tfvars.json

- В обоих `terraform.tfvars` указать одинаковые `cloud_id` и `folder_id`.
- В bootstrap задать глобально уникальное `state_bucket_name`.
- В `compute.auto.tfvars.json` заменить `YOUR_PUBLIC_IPV4/32` на исходящий
  публичный IPv4 управляющего хоста. Он нужен для SSH и Kubernetes API;
  адрес интерфейса локальной сети для этого не подходит.
- Проверить доступность закреплённого `ubuntu_image_id` в Yandex Cloud.
  Для другого образа Ubuntu 24.04 указать его ID до планирования.

Не добавлять эти файлы в Git. При изменении параметров впоследствии обновить
соответствующие GitHub Secrets до запуска Terraform CI.

Зеркало провайдера на управляющем хосте можно настроить отдельным файлом,
не перезаписывая общий `~/.terraformrc`:

    cat > .secrets/terraformrc <<'TFRC'
    provider_installation {
      network_mirror {
        url = "https://terraform-mirror.yandexcloud.net/"
        include = ["registry.terraform.io/yandex-cloud/yandex"]
      }
      direct {
        exclude = ["registry.terraform.io/yandex-cloud/yandex"]
      }
    }
    TFRC
    export TF_CLI_CONFIG_FILE="$PWD/.secrets/terraformrc"

Сохранять эту переменную в терминале, из которого запускаются Terraform
и использующие его скрипты. Все `.secrets`, state, планы и kubeconfig
остаются вне Git.

## 2. Bootstrap и ключи

Если bootstrap уже существует, использовать его сохранённый локальный state
и ключи. Отсутствие state при существующих ресурсах не означает, что нужно
создавать их заново. Для переноса управляющего хоста требуется резервная копия.

Первичное создание:

    (
      set -euo pipefail
      umask 077
      unset YC_SERVICE_ACCOUNT_KEY_FILE
      export YC_TOKEN="$(yc iam create-token)"
      test -n "$YC_TOKEN"
      terraform -chdir=terraform/bootstrap init -lockfile=readonly
      terraform -chdir=terraform/bootstrap validate
      terraform -chdir=terraform/bootstrap plan -out=bootstrap.tfplan
    )

Проверить план. Затем применить именно сохранённый план:

    (
      set -euo pipefail
      umask 077
      unset YC_SERVICE_ACCOUNT_KEY_FILE
      export YC_TOKEN="$(yc iam create-token)"
      terraform -chdir=terraform/bootstrap apply bootstrap.tfplan
      mkdir -p .secrets/bootstrap-backups
      cp terraform/bootstrap/terraform.tfstate ".secrets/bootstrap-backups/bootstrap-$(date +%Y%m%d-%H%M%S).tfstate"

      for account in terraform registry-puller registry-pusher; do
        case "$account" in
          terraform) output_name=terraform_service_account_id; key_file=.secrets/terraform-sa-key.json ;;
          registry-puller) output_name=registry_puller_service_account_id; key_file=.secrets/registry-puller-key.json ;;
          registry-pusher) output_name=registry_pusher_service_account_id; key_file=.secrets/registry-pusher-key.json ;;
        esac
        account_id="$(terraform -chdir=terraform/bootstrap output -raw "$output_name")"
        if [ ! -e "$key_file" ]; then
          yc iam key create --service-account-id "$account_id" --output "$key_file" >/dev/null
        fi
        test -s "$key_file"
        chmod 600 "$key_file"
      done
    )

Существующие файлы ключей должны относиться к аккаунтам этого bootstrap.
Не переносить ключи от другого каталога под теми же именами.
Ключи создаются отдельно через CLI и не управляются Terraform.

Проверить, что `bucket` в `terraform/infrastructure/backend.tf` совпадает
с выводом следующей команды. Для другого каталога изменить имя бакета в
`backend.tf` до первого `init` основной конфигурации:

    terraform -chdir=terraform/bootstrap output -raw state_bucket_name

Не менять backend действующего стенда без отдельной миграции state.

## 3. Основная инфраструктура

В текущем терминале определить функцию авторизации. Она читает S3-ключи
из локального bootstrap state, не выводя их:

    tf_credentials() {
      unset YC_TOKEN AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE
      export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-sa-key.json"
      test -s "$YC_SERVICE_ACCOUNT_KEY_FILE" || return
      AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap output -raw state_access_key)" || return
      AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap output -raw state_secret_key)" || return
      test -n "$AWS_ACCESS_KEY_ID" && test -n "$AWS_SECRET_ACCESS_KEY" || return
      export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_EC2_METADATA_DISABLED=true
    }

После открытия нового терминала заново задать `TF_CLI_CONFIG_FILE`
и определить эту функцию. Она ожидает текущий каталог — корень репозитория.

Перед локальным plan/apply убедиться, что нет параллельных CI-запусков.
В S3 backend этого стенда блокировки state нет.

    (
      set -euo pipefail
      umask 077
      tf_credentials
      python3 -m venv .secrets/registry-tools
      .secrets/registry-tools/bin/python -m pip install -r scripts/registry-tools-requirements.txt
      terraform -chdir=terraform/infrastructure init -lockfile=readonly
      terraform -chdir=terraform/infrastructure fmt -check
      terraform -chdir=terraform/infrastructure validate
      terraform -chdir=terraform/infrastructure plan -out=infrastructure.tfplan
    )

Для пустой основной конфигурации ожидается 10 создаваемых ресурсов:
VPC, три подсети, две группы безопасности, три ВМ и Registry.
После проверки плана:

    (
      set -euo pipefail
      umask 077
      tf_credentials
      terraform -chdir=terraform/infrastructure apply infrastructure.tfplan
      terraform -chdir=terraform/infrastructure plan
      terraform -chdir=terraform/infrastructure output -json > .secrets/infrastructure-outputs.json
      terraform -chdir=terraform/infrastructure output -json nodes | python3 scripts/generate-inventory.py
    )

Повторный plan должен показать `No changes`. Адреса и ID берутся из новых
outputs; после пересоздания они изменяются.

## 4. SSH и Kubernetes

Для каждого узла сопоставить ID ВМ и публичный IP из Terraform outputs.
Получить отпечатки SSH host keys из доверенного вывода serial port этой ВМ
в консоли Yandex Cloud либо через `yc compute instance get-serial-port-output`.
При первом SSH-подключении сравнить показанный отпечаток с этим выводом
и только при совпадении принять ключ. Проверить все три узла.
При повторном использовании старого IP удалять старую запись known_hosts
можно после проверки, что IP относится именно к новой ВМ.

Источник: [вывод serial port Yandex Cloud](https://yandex.cloud/en/docs/compute/operations/vm-info/get-serial-port-output).

Узлы должны отвечать пользователю `ubuntu`, а `sudo -n true` — завершаться
успешно. Например, подставить фактический IP узла:

    read -r -p 'Публичный IP проверяемого узла: ' NODE_IP
    ssh -i "$HOME/.ssh/id_ed25519" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes "ubuntu@$NODE_IP" 'sudo -n true'

При установке на полностью новые ВМ перенести прежний каталог
`ansible/inventory/diplom/artifacts` в защищённую резервную копию до запуска.
Не подставлять старый admin.conf в новый кластер.

Установка использует сгенерированный inventory и параметры метрик из
`ansible/inventory/diplom/group_vars/all/monitoring.yml`:

    ./scripts/run-kubespray.sh

После успешного playbook установить полученные артефакты:

    (
      set -euo pipefail
      umask 077
      install -d -m 0700 "$HOME/.kube"
      if [ -f "$HOME/.kube/config" ]; then
        cp -p "$HOME/.kube/config" ".secrets/admin-kubeconfig-before-$(date +%Y%m%d-%H%M%S)"
      fi
      sudo install -o "$(id -u)" -g "$(id -g)" -m 0600 ansible/inventory/diplom/artifacts/admin.conf "$HOME/.kube/config"
      sudo install -o root -g root -m 0755 ansible/inventory/diplom/artifacts/kubectl /usr/local/bin/kubectl
      export KUBECONFIG="$HOME/.kube/config"
      kubectl get nodes -o wide
      kubectl get pods --all-namespaces
    )

Ожидаются три узла Ready и готовые системные поды.
Дальнейшие команды используют `~/.kube/config`; если ранее переменная
KUBECONFIG указывала другой путь, задать `export KUBECONFIG="$HOME/.kube/config"`.

## 5. Traefik и мониторинг

Установить HTTP-контроллер:

    (
      set -euo pipefail
      kubectl apply -f kubernetes/traefik/namespace.yaml
      helm repo add traefik https://traefik.github.io/charts --force-update
      helm upgrade --install traefik traefik/traefik --namespace ingress-system --version "$(cat kubernetes/traefik/chart-version.txt)" --values kubernetes/traefik/values.yaml --wait --timeout 5m
      kubectl -n ingress-system get daemonset,pods -o wide
    )

Ожидаются два готовых pod Traefik на workers. До появления Ingress
ответ 404 на корневой путь сам по себе не означает неисправность контроллера.

### Первый запуск Grafana

При восстановлении использовать имеющийся `.secrets/grafana-admin-secret.json`:
следующий блок пропустить. Если нет ни Secret, ни его копии, создать первоначальный
Secret с вводом пароля без отображения. Не выполнять этот блок для смены пароля
у уже существующей базы Grafana.

    kubectl apply -f kubernetes/monitoring/namespace.yaml
    python3 - <<'PY'
    import base64
    import getpass
    import json
    from pathlib import Path
    import subprocess

    if Path('.secrets/grafana-admin-secret.json').exists():
        raise SystemExit('Есть резервная копия Secret; используйте восстановление')
    password = getpass.getpass('Новый пароль администратора Grafana: ')
    if not password or password != getpass.getpass('Повторите пароль: '):
        raise SystemExit('Пустой пароль или значения не совпали')
    document = {
        'apiVersion': 'v1', 'kind': 'Secret',
        'metadata': {'name': 'grafana-admin', 'namespace': 'monitoring'},
        'type': 'Opaque',
        'data': {
            'admin-user': base64.b64encode(b'admin').decode(),
            'admin-password': base64.b64encode(password.encode()).decode(),
        },
    }
    result = subprocess.run(
        ['kubectl', '--request-timeout=30s', 'create', '-f', '-'],
        input=json.dumps(document), text=True, capture_output=True,
    )
    if result.returncode:
        raise SystemExit('Secret не создан: проверьте наличие Secret и доступ к кластеру')
    print('Secret monitoring/grafana-admin создан')
    PY

Если нужно сохранить историю, восстановить архивы локальных PV до установки
Helm-релиза: порядок приведён в разделе 9. Для нового стенда каталоги пустые.

    ./scripts/deploy-monitoring.sh
    kubectl -n monitoring get pods,pvc -o wide

Скрипт создаёт каталоги и PV, сохраняет или восстанавливает Secret, формирует
адреса из Terraform и устанавливает закреплённый chart. Не применять только
базовый `values.yaml` с адресами от чужой или предыдущей установки.

Проверить три PVC Bound, готовность всех pod и URL Grafana из вывода скрипта.
После нескольких scrape-интервалов проверить targets:

    kubectl --request-timeout=30s get --raw '/api/v1/namespaces/monitoring/services/http:monitoring-prometheus:9090/proxy/api/v1/targets?state=active' |
      python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print("Targets:",len(t),"UP:",sum(x["health"]=="up" for x in t)); [print(x["scrapeUrl"],x.get("lastError","")) for x in t if x["health"]!="up"]; sys.exit(0 if len(t)==28 and all(x["health"]=="up" for x in t) else 1)'

28 targets — проверенный состав этого стенда. При намеренном изменении
набора ServiceMonitor количество может измениться.
В Grafana открыть дашборды Kubernetes и убедиться, что есть данные трёх узлов.

Для кластера, установленного до добавления параметра kube-proxy,
при отсутствии его метрик предусмотрен отдельный однократный шаг:

    python3 scripts/configure-kube-proxy-metrics.py
    kubectl -n kube-system rollout restart daemonset/kube-proxy
    kubectl -n kube-system rollout status daemonset/kube-proxy

На проверенной новой установке Kubespray этот дополнительный шаг не потребовался.

## 6. Первая публикация приложения и доступ CD

Создать отдельного пользователя на управляющем хосте, если его ещё нет.
Он не должен состоять в группах sudo и docker:

    if ! id diplom-runner >/dev/null 2>&1; then
      sudo useradd --create-home --user-group --shell /bin/bash diplom-runner
    fi
    id diplom-runner

Новый Registry пуст. Сначала собрать, проверить и опубликовать образ,
затем развернуть его и подготовить kubeconfig runner:

    (
      set -euo pipefail
      umask 077
      tf_credentials
      APP_REPOSITORY="$(terraform -chdir=terraform/infrastructure output -raw app_image_repository)"
      unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
      [[ "$APP_REPOSITORY" =~ ^cr\.yandex/[a-z0-9]+/devops-diplom-app$ ]]
      test -z "$(git -C "$HOME/devops-diplom-app" status --porcelain)"
      APP_TAG="sha-$(git -C "$HOME/devops-diplom-app" rev-parse --short=12 HEAD)"
      APP_IMAGE="$APP_REPOSITORY:$APP_TAG"
      docker build --pull -t "$APP_IMAGE" "$HOME/devops-diplom-app"
      "$HOME/devops-diplom-app/scripts/test-image.sh" "$APP_IMAGE"
      REGISTRY_AUTH_DIR="$(mktemp -d)"
      trap 'rm -rf -- "$REGISTRY_AUTH_DIR"' EXIT
      docker --config "$REGISTRY_AUTH_DIR" login --username json_key --password-stdin cr.yandex < .secrets/registry-pusher-key.json
      docker --config "$REGISTRY_AUTH_DIR" push "$APP_IMAGE"
      PUBLISHED_IMAGE="$(docker image inspect "$APP_IMAGE" --format '{{json .RepoDigests}}' | python3 -c 'import json,sys; p=sys.argv[1]+"@sha256:"; m=[x for x in json.load(sys.stdin) if x.startswith(p)]; assert len(m)==1,m; print(m[0])' "$APP_REPOSITORY")"
      ./scripts/restore-app.sh "${PUBLISHED_IMAGE##*@}"
    )

Ожидаются Deployment 2/2 и две реплики на разных workers.
`restore-app.sh` создаёт pull Secret, манифесты приложения, ограниченный RBAC
для app-deployer и устанавливает его kubeconfig пользователю diplom-runner.
Это также обновляет доступ после пересоздания кластера.

Приватный Registry требует авторизации. Публичные адреса страницы и `/healthz`
получать из Terraform outputs; проверять оба worker.

## 7. GitHub Actions приложения

Перед включением pipeline задать ключ публикации и переменные:

    (
      set -euo pipefail
      gh secret set YC_REGISTRY_PUSHER_KEY --repo victoryurochkin/devops-diplom-app < .secrets/registry-pusher-key.json
      tf_credentials
      terraform -chdir=terraform/infrastructure output -json | python3 scripts/sync-app-ci-vars.py
      gh variable list --repo victoryurochkin/devops-diplom-app
    )

### CD-runner

В репозитории приложения открыть Settings → Actions → Runners → New self-hosted
runner, выбрать Linux x64. Использовать предлагаемые GitHub команды скачивания
и проверки SHA256 актуального архива. Проверенная первоначальная версия
зафиксирована в `docs/github-runner-version.txt`; runner допускает автообновления.

Подготовить каталог:

    sudo install -d -o diplom-runner -g diplom-runner -m 0750 /home/diplom-runner/actions-runner

Распаковать проверенный архив в этот каталог от пользователя diplom-runner.
Установить системные зависимости через
`sudo /home/diplom-runner/actions-runner/bin/installdependencies.sh`.

Регистрацию выполнять от diplom-runner из `/home/diplom-runner/actions-runner`.
Использовать `config.sh`, URL репозитория приложения и одноразовый токен,
выданный GitHub. Задать имя `diplom-app-deploy-it`, дополнительную метку
`diplom-deploy`, рабочий каталог `_work`. Стандартные метки self-hosted,
Linux и X64 оставить включёнными. Токен не сохранять в репозитории.
Если runner уже зарегистрирован и online, повторная регистрация не нужна.

Установить службу после успешной регистрации:

    sudo bash <<'ROOT'
    set -euo pipefail
    export SYSTEMD_PAGER=cat
    cd /home/diplom-runner/actions-runner
    if [ ! -f .service ]; then
      ./svc.sh install diplom-runner
    fi
    ./svc.sh start
    ./svc.sh status
    ROOT

Проверить статус online в GitHub. Проверить доступ к Deployment:

    sudo -u diplom-runner -H /usr/local/bin/kubectl --kubeconfig=/home/diplom-runner/.kube/config --request-timeout=30s -n diplom-app get deployment diplom-app

Источник процедуры регистрации:
[GitHub: adding self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners).

### Сборка и релиз

Включить workflow, если он был отключён:

    gh workflow enable app.yml --repo victoryurochkin/devops-diplom-app

Обычный push запускает build, test и push образа. Проверить завершение в Actions.
Для деплоя создать новый, ещё не существующий Git-тег на проверенном коммите
приложения и отправить именно этот тег. Уже выпущенные теги не переносить.
Например, для следующего релиза после v1.0.1:

    (
      set -euo pipefail
      cd "$HOME/devops-diplom-app"
      test -z "$(git status --porcelain)"
      git tag -a v1.0.2 -m "Diploma application release v1.0.2"
      git push origin refs/tags/v1.0.2
    )

Этот пример действительно выпускает новую версию; для просмотра существующих
результатов достаточно ссылки на проверенный релиз, выполнять его не требуется.
Успешный workflow содержит build/test/push и Deploy tagged release с rollout
и HTTP-проверками. При обычном push в ветку deploy будет skipped — это ожидаемо.
Временная ошибка Registry 503 в проверке v1.0.1 устранена повтором failed job;
тег при этом не изменялся.

## 8. GitHub Actions Terraform

Параметры Secrets должны совпадать с локальными файлами, по которым создан стенд:

    (
      set -euo pipefail
      TF_REPO=victoryurochkin/devops-diplom-yandexcloud
      gh secret set YC_TERRAFORM_KEY --repo "$TF_REPO" < .secrets/terraform-sa-key.json
      terraform -chdir=terraform/bootstrap output -raw state_access_key | gh secret set TF_STATE_ACCESS_KEY_ID --repo "$TF_REPO"
      terraform -chdir=terraform/bootstrap output -raw state_secret_key | gh secret set TF_STATE_SECRET_ACCESS_KEY --repo "$TF_REPO"
      gh secret set TF_VARS --repo "$TF_REPO" < terraform/infrastructure/terraform.tfvars
      gh secret set TF_COMPUTE_VARS --repo "$TF_REPO" < terraform/infrastructure/compute.auto.tfvars.json
      gh secret set TF_SSH_PUBLIC_KEY --repo "$TF_REPO" < "$HOME/.ssh/id_ed25519.pub"
      gh workflow enable terraform.yml --repo "$TF_REPO"
    )

Каждый push в main запускает fmt/init/validate/plan/apply без фильтра путей.
Первую проверку можно запустить вручную:

    gh workflow run terraform.yml --repo victoryurochkin/devops-diplom-yandexcloud --ref main
    gh run list --repo victoryurochkin/devops-diplom-yandexcloud --limit 5

Дождаться завершения конкретного запуска. Ожидаются `No changes` и
`Apply complete! Resources: 0 added, 0 changed, 0 destroyed.`
Workflow применяет только `terraform/infrastructure`; bootstrap остаётся отдельным.
Concurrency сериализует CI, но не защищает от параллельного локального Terraform.

## 9. Повторное создание основной инфраструктуры

Это отдельная операция с простоем и удалением всех образов Registry,
ВМ и их дисков. Bootstrap и бакет со state не удаляются.
Для демонстрации уже получены результаты 28.09.2026; повторять удаление
для подготовки документации не нужно.

### Подготовка и резервные копии

1. Отключить оба workflow и дождаться завершения всех текущих запусков:

       gh workflow disable terraform.yml --repo victoryurochkin/devops-diplom-yandexcloud
       gh workflow disable app.yml --repo victoryurochkin/devops-diplom-app

2. В каталог вне репозиториев с правами 0700 сохранить git bundle обоих
   репозиториев; `.secrets`; локальные tfvars; bootstrap state; inventory;
   административный и runner kubeconfig; текущие Terraform outputs и копию
   удалённого state (`terraform state pull` с авторизацией из раздела 3).
   Это резервная копия: старый state нельзя записывать поверх state новых ресурсов.
3. Сохранить работающий образ приложения через `docker image save`, проверить
   архив загрузкой и `scripts/test-image.sh`. Сохранить ссылку по digest.
   Альтернатива для нового стенда — повторная сборка из зафиксированного Git-коммита.
4. Для сохранения истории мониторинга записать исходные replicas, остановить
   Grafana Deployment, Prometheus CR и Alertmanager CR, задав replicas=0.
   Дождаться удаления использующих PV pod. Скопировать каталоги с помощью tar
   с сохранением numeric owner, ACL и xattrs. Затем вернуть исходное число
   replicas и проверить готовность. Не архивировать работающие базы как
   гарантированно согласованную резервную копию.

Соответствие архивов данным:

| Узел | Каталоги под `/var/lib/diplom-monitoring` |
|---|---|
| worker-1 | `grafana`, `alertmanager` |
| worker-2 | `prometheus` |

Архивы этого проекта содержат каталоги относительно `/var/lib/diplom-monitoring`.
Создание выполнялось с `tar --numeric-owner --acls --xattrs -C /var/lib/diplom-monitoring`.
Проверить чтение архивов и SHA256 до удаления. Не публиковать архивы, state,
логи с возможными секретами и kubeconfig в Git.

### Destroy и apply

Сохранить актуальную конфигурацию Registry с destroy provisioner и установленное
окружение `.secrets/registry-tools`. Из корня репозитория с авторизацией раздела 3:

    (
      set -euo pipefail
      umask 077
      tf_credentials
      terraform -chdir=terraform/infrastructure plan -destroy -out=destroy.tfplan
    )

Проверить: план содержит только 10 удалений основной конфигурации,
ресурсов bootstrap в нём нет. Применение выполняется отдельной командой
после проверки резервных копий и состава плана:

    (
      set -euo pipefail
      tf_credentials
      terraform -chdir=terraform/infrastructure apply destroy.tfplan
      terraform -chdir=terraform/infrastructure state list
    )

Очистка образов запускается автоматически перед удалением Registry.
Пустой state основной конфигурации остаётся в S3. Не удалять bootstrap state
и не запускать destroy в каталоге bootstrap.
Затем повторить plan/apply основной конфигурации из раздела 3:
ожидаются 10 созданий и повторный `No changes`.

### Восстановление сервисов

1. Сформировать новый inventory, проверить новые SSH host keys и установить
   Kubernetes по разделу 4. Обновить admin kubeconfig.
2. Для сохранения истории до запуска мониторинга восстановить архивы на
   соответствующих новых workers в `/var/lib/diplom-monitoring`.
   Проверить список путей в архиве, свободные целевые каталоги и контрольные суммы.
   Извлекать от root с `tar --numeric-owner --same-owner --acls --xattrs`.
   Не распаковывать поверх работающих данных.
3. Проверить владельцев восстановленных каталогов: Grafana UID/GID 472/472,
   Prometheus и Alertmanager — 0/2000 в проверенной копии. Сохранять владельцев
   из архива; не назначать 0777 всем данным.
4. Установить Traefik и выполнить `./scripts/deploy-monitoring.sh`.
   Он восстановит Secret из локальной копии и подставит новые IP.
5. Опубликовать образ в новом Registry. Старый Registry ID уже недействителен.
   Для новой сборки использовать раздел 6. Для сохранённого Docker-архива
   использовать Skopeo `copy` с источником `docker-archive:...`, целевым
   `docker://НОВЫЙ_РЕПОЗИТОРИЙ:ТЕГ`, авторизацией json_key и `--digestfile`.
   При переносе проверенного архива применялся `--format v2s2`.
6. При проверке архивного образа сравнивать SHA256 конфигурации из файла Config,
   указанного в `manifest.json` архива, с `config.digest` опубликованного манифеста.
   `docker image inspect .Id` в использованном хранилище не подошёл для этого
   сравнения. Digest манифеста может измениться при перепубликации.
7. Запустить `./scripts/restore-app.sh` с digest, полученным в новом Registry.
   Скрипт восстановит приложение и заменит kubeconfig существующего CD-runner.
8. Выполнить `scripts/sync-app-ci-vars.py` из раздела 7. Обновятся
   IMAGE_REPOSITORY и APP_WORKER_IPS. Проверить runner online.
9. Проверить метрики, приложение, `/healthz`, Grafana и исторический запрос
   до времени удаления. Восстановление файла Secret не восстанавливает базу
   Grafana или историю Prometheus — для них нужны архивы PV.
10. Включить оба workflow, проверить Terraform CI и выпустить новый Git-тег
    приложения для проверки CD. Обновить текущие ссылки README и закреплённый
    образ deployment.yaml после успешного релиза. Исторические отчёты не переписывать.

## 10. Проверки и материалы сдачи

Проверить перед сдачей:

- Три узла Ready, системные pod готовы.
- Приложение: Deployment 2/2, реплики на разных workers, HTTP на порту 80,
  правильная страница и ответ `ok` от `/healthz`.
- Мониторинг: три PVC Bound, 28/28 targets UP и данные Kubernetes в Grafana.
- CI приложения: обычный push собирает, тестирует и публикует sha-образ;
  push тега дополнительно развёртывает образ по digest.
- Terraform CI: push в main запускает plan и apply; показан успешный результат.
- В README указаны актуальные адреса. Для проверяющего подготовлены отдельные
  данные доступа Grafana, передаваемые вместе со сдачей вне публичного Git.

В интерфейсе Actions сохранить скриншоты Terraform plan/apply и релизного
build/test/push/deploy. Дополнительно — страницу приложения и дашборд Grafana
с данными трёх узлов. Текстовые отчёты дополняют требуемые скриншоты CI.

Проверенные результаты:

- [Автоматический Terraform CI после push 2cefd21](https://github.com/victoryurochkin/devops-diplom-yandexcloud/actions/runs/36429844498): No changes, apply 0/0/0.
- [CI приложения после push e72cb98](https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36429850386): сборка, тесты, push успешны; deploy пропущен для ветки.
- [Релиз v1.0.1, успешная попытка 2](https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36427694065): автоматический деплой в пересозданный кластер.
- [Проверка текущего релиза](app-release-after-recreate-check.txt).
- [Проверка мониторинга после пересоздания](monitoring-after-recreate-check.txt).
- [Сохранённая история Prometheus](monitoring-history-check.txt).
- [Восстановление архивного образа](app-after-recreate-check.txt).

Ограничения учебного стенда: один control plane, прерываемые workers,
локальные PV, отсутствие блокировки state между CI и локальными запусками,
долгоживущий токен ограниченного ServiceAccount деплоя. Внешние уведомления
Alertmanager не настроены. Дополнительные системы CI/CD, домен и облачный
балансировщик для выполнения выбранного варианта задания не используются.
