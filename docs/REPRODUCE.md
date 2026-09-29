# Воспроизведение и эксплуатация

Стенд отключён, включая bootstrap. Для восстановления из резервной копии сначала
прочитать [порядок после полного удаления](DECOMMISSION.md#повторное-развёртывание):
нужны новые state, сервисные аккаунты, ключи и адреса. Эта инструкция описывает
создание нового действующего стенда.

Инструкция выполняется на управляющем Linux x86_64 хосте. На нём нужны Bash,
Git, Docker, Python 3/venv, curl, sudo, Yandex Cloud CLI, GitHub CLI и Helm 3.
Хост также обслуживает CD-runner и systemd timer; он должен оставаться включённым.

## 1. Исходные данные

Настроить yc init для своего облака и каталога с действующим платёжным аккаунтом.
Проверить свободные квоты: три ВМ, три публичных адреса, SSD-диски по 30 ГБ.
Отдельно проверить квоту статических публичных адресов
vpc.externalStaticAddresses.count: для стенда нужны три адреса. Стандартное
значение — два; увеличение запрашивается в разделе «Квоты» облака до создания
или импорта адресов. Если в облаке есть другие статические IP, учесть их занятость.
Подробнее: [квоты VPC](https://yandex.cloud/ru/docs/vpc/concepts/limits).
Выполнить gh auth login и настроить SSH-доступ к GitHub.

    git clone git@github.com:victoryurochkin/devops-diplom-yandexcloud.git
    git clone git@github.com:victoryurochkin/devops-diplom-app.git
    cd devops-diplom-yandexcloud
    umask 077
    mkdir -p .secrets
    chmod 700 .secrets
    ./scripts/install-terraform.sh

Все последующие команды выполняются из корня инфраструктурного репозитория,
если не указано иное. Используется SSH-пара ~/.ssh/id_ed25519; при её отсутствии
создать новую через ssh-keygen, не перезаписывая существующие ключи.

    cp -n terraform/bootstrap/terraform.tfvars.example terraform/bootstrap/terraform.tfvars
    cp -n terraform/infrastructure/terraform.tfvars.example terraform/infrastructure/terraform.tfvars
    cp -n terraform/infrastructure/compute.auto.tfvars.json.example terraform/infrastructure/compute.auto.tfvars.json

Заполнить cloud_id и folder_id, уникальное имя бакета bootstrap. В compute.auto.tfvars.json
указать исходящий публичный IPv4 управляющего хоста с маской /32 в admin_cidrs.
Проверить доступность ubuntu_image_id или указать другой образ Ubuntu 24.04.
Для своей копии проекта заменить имена GitHub-репозиториев в командах и sync-app-ci-vars.py.
Файлы параметров, ключи, планы, state и kubeconfig не добавляются в Git.

Настроить зеркало провайдера и экспортировать путь в текущем терминале:

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

## 2. Bootstrap

При существующем bootstrap использовать сохранённые локальный state и ключи.
Нельзя создавать дубли ресурсов вместо восстановления отсутствующего state.
Для первичной установки нужны пользовательские права на создание сервисных
аккаунтов, назначение сервисных ролей, выпуск ключей и создание S3-бакета.

    (
      set -euo pipefail
      unset YC_SERVICE_ACCOUNT_KEY_FILE
      export YC_TOKEN="$(yc iam create-token)"
      terraform -chdir=terraform/bootstrap init -lockfile=readonly
      terraform -chdir=terraform/bootstrap validate
      terraform -chdir=terraform/bootstrap plan -out=bootstrap.tfplan
    )

После проверки плана применить его и сохранить state:

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

Сверить bucket в terraform/infrastructure/backend.tf с output state_bucket_name.
Для нового каталога изменить bucket до первого init. Для работающего стенда
не менять backend без отдельной миграции state.

## 3. Облачная инфраструктура

Основная конфигурация создаёт 13 ресурсов: VPC, три подсети, две группы безопасности,
три ВМ, три статических публичных адреса и Container Registry.
Скрипт with-cloud-env.sh задаёт сервисный ключ Terraform и S3-ключи из bootstrap;
значения ключей не выводятся. Срок ожидания state lock — пять минут.

    python3 -m venv .secrets/registry-tools
    .secrets/registry-tools/bin/pip install -r scripts/registry-tools-requirements.txt
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure init -lockfile=readonly
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure validate
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure plan -out=infrastructure.tfplan

После проверки плана:

    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure apply infrastructure.tfplan
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure plan
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure output -json nodes | python3 scripts/generate-inventory.py

Повторный plan должен показать No changes.
S3 lockfile защищает локальные и CI-запуски; не использовать -lock=false.
При прерывании Terraform не удалять lock вручную до проверки отсутствия работающего процесса.

Проверка блокировки при отсутствии активных Terraform-запусков:

    ./scripts/with-cloud-env.sh python3 scripts/check-state-lock.py

Скрипт удерживает lock через terraform console, проверяет отказ конкурирующего
plan и успешный план после штатного выхода из консоли. Apply не выполняется.

## 4. Kubernetes

Получить SSH host key fingerprints из serial port каждой ВМ через консоль
Yandex Cloud или yc compute instance get-serial-port-output. При первом SSH-входе
сравнить отпечаток с доверенным выводом. Проверить все три узла и sudo -n true
от ubuntu. Старую запись known_hosts удалять только после проверки нового владельца IP.

Если устанавливается новый кластер, перенести старый ansible/inventory/diplom/artifacts
в защищённую копию. Не подставлять старый admin.conf в новый кластер.

    ./scripts/run-kubespray.sh
    install -d -m 0700 "$HOME/.kube"
    sudo install -o "$(id -u)" -g "$(id -g)" -m 0600 ansible/inventory/diplom/artifacts/admin.conf "$HOME/.kube/config"
    sudo install -o root -g root -m 0755 ansible/inventory/diplom/artifacts/kubectl /usr/local/bin/kubectl
    export KUBECONFIG="$HOME/.kube/config"
    kubectl get nodes -o wide
    kubectl get pods --all-namespaces

Ожидаются три Ready узла и готовые системные pod. Параметры публикации метрик
сохранены в ansible/inventory/diplom/group_vars/all/monitoring.yml.

## 5. Traefik и мониторинг

    kubectl apply -f kubernetes/traefik/namespace.yaml
    helm repo add traefik https://traefik.github.io/charts --force-update
    helm upgrade --install traefik traefik/traefik --namespace ingress-system --version "$(cat kubernetes/traefik/chart-version.txt)" --values kubernetes/traefik/values.yaml --wait --timeout 5m
    kubectl -n ingress-system get daemonset,pods -o wide

Для первой установки Grafana создать Secret. При наличии сохранённого
.secrets/grafana-admin-secret.json этот блок пропустить. Он не предназначен
для смены пароля уже существующей базы Grafana.

    kubectl apply -f kubernetes/monitoring/namespace.yaml
    python3 - <<'PYCODE'
    import base64
    import getpass
    import json
    from pathlib import Path
    import subprocess
    if Path('.secrets/grafana-admin-secret.json').exists():
        raise SystemExit('Используйте существующую копию Secret')
    password = getpass.getpass('Пароль администратора Grafana: ')
    if not password or password != getpass.getpass('Повторите пароль: '):
        raise SystemExit('Пустой пароль или значения не совпадают')
    document = {
        'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
        'metadata': {'name': 'grafana-admin', 'namespace': 'monitoring'},
        'data': {
            'admin-user': base64.b64encode(b'admin').decode(),
            'admin-password': base64.b64encode(password.encode()).decode(),
        },
    }
    result = subprocess.run(['kubectl', 'create', '-f', '-'],
        input=json.dumps(document), text=True, capture_output=True)
    if result.returncode:
        raise SystemExit('Secret не создан: проверьте доступ и существующие Secrets')
    print('Secret Grafana создан')
    PYCODE

Если требуется сохранить данные, восстановить архивы PV до установки Helm-релиза.
Для новой установки каталоги создаются пустыми.

    ./scripts/deploy-monitoring.sh
    kubectl -n monitoring get pods,pvc -o wide

Скрипт подготавливает каталоги и PV, сохраняет или восстанавливает Secret,
получает IP из Terraform outputs и применяет chart с runtime values.
Проверить три PVC Bound, готовые pod и дашборды Grafana.

## 6. Приложение

    if ! id diplom-runner >/dev/null 2>&1; then
      sudo useradd --create-home --user-group --shell /bin/bash diplom-runner
    fi

Первичная публикация в пустой Registry:

    (
      set -euo pipefail
      umask 077
      APP_REPOSITORY="$(./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure output -raw app_image_repository)"
      test -z "$(git -C "$HOME/devops-diplom-app" status --porcelain)"
      APP_TAG="sha-$(git -C "$HOME/devops-diplom-app" rev-parse --short=12 HEAD)"
      APP_IMAGE="$APP_REPOSITORY:$APP_TAG"
      docker build --pull -t "$APP_IMAGE" "$HOME/devops-diplom-app"
      "$HOME/devops-diplom-app/scripts/test-image.sh" "$APP_IMAGE"
      REGISTRY_AUTH_DIR="$(mktemp -d)"
      trap 'rm -rf -- "$REGISTRY_AUTH_DIR"' EXIT
      docker --config "$REGISTRY_AUTH_DIR" login --username json_key --password-stdin cr.yandex < .secrets/registry-pusher-key.json
      "$HOME/devops-diplom-app/scripts/retry.sh" docker --config "$REGISTRY_AUTH_DIR" push "$APP_IMAGE"
      PUBLISHED_IMAGE="$(docker image inspect "$APP_IMAGE" --format '{{json .RepoDigests}}' | python3 -c 'import json,sys; p=sys.argv[1]+"@sha256:"; m=[x for x in json.load(sys.stdin) if x.startswith(p)]; assert len(m)==1,m; print(m[0])' "$APP_REPOSITORY")"
      ./scripts/restore-app.sh "${PUBLISHED_IMAGE##*@}"
    )

Ожидается Deployment 2/2 на разных workers. restore-app.sh подставляет текущий
Registry и переданный digest, создаёт pull Secret, приложение и ограниченный RBAC CD.
Не применять deployment.yaml для обновления уже выпущенного через CD релиза:
версию задают через Git-тег или явный digest при восстановлении.

## 7. CI/CD и обслуживание

    gh secret set YC_REGISTRY_PUSHER_KEY --repo victoryurochkin/devops-diplom-app < .secrets/registry-pusher-key.json
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure output -json | python3 scripts/sync-app-ci-vars.py

sync-app-ci-vars.py обновляет IMAGE_REPOSITORY и APP_WORKER_IPS, затем сохраняет
публичные метаданные узлов для обслуживания. Выполнить его после каждого пересоздания.

Зарегистрировать Linux x64 runner по командам Settings → Actions → Runners
репозитория приложения. Скачать официальный архив, проверить SHA256,
распаковать в /home/diplom-runner/actions-runner от diplom-runner.
Установить зависимости через bin/installdependencies.sh от root.
Выполнить config.sh от diplom-runner с URL репозитория, одноразовым токеном,
именем diplom-app-deploy-it и меткой diplom-deploy. Сохранить стандартные метки.
Пользователь runner не включается в sudo или docker.

    sudo bash <<'ROOT'
    set -euo pipefail
    cd /home/diplom-runner/actions-runner
    if [ ! -f .service ]; then ./svc.sh install diplom-runner; fi
    ./svc.sh start
    ./svc.sh status
    ROOT
    sudo ./scripts/install-maintenance.sh "$HOME/.kube/config"
    gh workflow enable app.yml --repo victoryurochkin/devops-diplom-app

Timer обновляет краткоживущий kubeconfig CD и запускает остановленные workers.
Файл содержит только токен app-deployer; runner не получает администраторские ключи.
Для ручного обновления выполнить ./scripts/refresh-deployer-access.sh.

Настроить Terraform Secrets и включить pipeline:

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

Каждый push в main выполняет plan/apply. Если изменены локальные tfvars,
обновить соответствующие Secrets до следующего запуска CI.
Обычный push приложения запускает build/test/push; новый Git-тег дополнительно
запускает CD. Существующие релизные теги не перемещаются.

## 8. Проверка и обслуживание

    kubectl get nodes -o wide
    kubectl get pods --all-namespaces
    kubectl -n diplom-app get deployment,pods -o wide
    kubectl -n monitoring get pods,pvc
    systemctl status diplom-maintenance.timer --no-pager
    sudo journalctl -u diplom-maintenance.service -n 40 --no-pager

Проверка Prometheus после нескольких scrape-интервалов:

    kubectl --request-timeout=30s get --raw '/api/v1/namespaces/monitoring/services/http:monitoring-prometheus:9090/proxy/api/v1/targets?state=active' |
      python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print("Targets:",len(t),"UP:",sum(x["health"]=="up" for x in t)); sys.exit(0 if len(t)==28 and all(x["health"]=="up" for x in t) else 1)'

Проверить HTTP страницу, /healthz и /grafana/api/health на обоих workers.
Открыть Grafana и проверить заполненные графики Kubernetes.
Для проверяющего передать отдельные данные доступа Grafana вне публичного Git.

Перед плановой остановкой, удалением или заменой ВМ:

    touch .secrets/maintenance.pause
    sudo systemctl stop diplom-maintenance.timer
    while systemctl is-active --quiet diplom-maintenance.service; do sleep 1; done
    gh workflow disable terraform.yml --repo victoryurochkin/devops-diplom-yandexcloud
    gh workflow disable app.yml --repo victoryurochkin/devops-diplom-app

Дождаться завершения всех CI-запусков. Флаг запрещает запуск workers и обновление
токена; уже выполняющийся запрос запуска ВМ может завершиться, поэтому нужно
дождаться остановки службы. Возобновление после проверки стенда:

    rm -f .secrets/maintenance.pause
    sudo systemctl start diplom-maintenance.timer
    sudo systemctl start diplom-maintenance.service
    gh workflow enable terraform.yml --repo victoryurochkin/devops-diplom-yandexcloud
    gh workflow enable app.yml --repo victoryurochkin/devops-diplom-app

## 9. Удаление и повторное создание

Для завершения работы после сдачи, включая архивирование и последующее удаление
bootstrap, использовать [DECOMMISSION.md](DECOMMISSION.md). Скрипт
`scripts/archive-stand.py` сохраняет данные и готовит проверенный destroy plan.
Порядок ниже относится к пересозданию основной инфраструктуры с сохранением bootstrap.

Сначала выполнить паузу обслуживания и CI из раздела 8. Сохранить вне репозиториев:
bootstrap state, .secrets, tfvars, inventory, kubeconfig, git bundle обоих репозиториев,
основной state через terraform state pull и outputs. Проверить читаемость архивов.

Если нужны данные мониторинга, записать исходные replicas и остановить Grafana
Deployment, Prometheus CR и Alertmanager CR (replicas=0). Дождаться удаления pod,
архивировать каталоги /var/lib/diplom-monitoring с numeric owner, ACL и xattrs:
worker-1 — grafana/alertmanager, worker-2 — prometheus. Затем вернуть replicas.
Образ можно собрать заново из Git-коммита или сохранить через docker image save.

    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure plan -destroy -out=destroy.tfplan

Проверить состав плана: только основная конфигурация, bootstrap и S3-бакета нет.
Удаляются также образы Registry, ВМ и их диски, публичные адреса. После проверки:

    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure apply destroy.tfplan
    ./scripts/with-cloud-env.sh terraform -chdir=terraform/infrastructure state list

Ожидается пустой основной state. Затем повторить разделы 3–7. Старый state
не записывать поверх состояния новых ресурсов. При восстановлении PV извлекать
архивы на соответствующие workers до Helm, сохраняя владельцев. Secret Grafana
содержит пароль, но не заменяет резервную копию базы.

Для образа из Docker-архива использовать Skopeo copy с источником docker-archive,
новым Registry, json_key и --digestfile; полученный digest передать restore-app.sh.
При новой сборке использовать раздел 6. После восстановления выполнить sync-app-ci-vars.py,
обновить адреса README/SUBMISSION, проверить приложение, мониторинг и новый релиз CI/CD.
