# Дипломный практикум DevOps в Yandex Cloud

Автор: Виктор Юрочкин.

Задание: https://github.com/netology-code/devops-diplom-yandexcloud

## Текущий статус

- [x] Создан отдельный каталог Yandex Cloud.
- [x] Через Terraform созданы сервисный аккаунт и закрытый S3-бакет.
- [x] Включено версионирование бакета.
- [x] Основной Terraform state хранится в S3.
- [x] От сервисного аккаунта созданы VPC и три подсети.
- [x] Повторный terraform plan подтверждает отсутствие изменений.
- [ ] Проверено удаление и повторное создание основной инфраструктуры.
- [x] Созданы виртуальные машины и группы безопасности.
- [x] Установлен Kubernetes.
- [x] Установлен Traefik, проверен входящий HTTP-трафик.
- [x] Развёрнут мониторинг, Grafana доступна по HTTP, 28/28 targets UP.
- [x] Созданы репозиторий приложения, Dockerfile и образ в registry.
- [x] Тестовое приложение развёрнуто и доступно по HTTP.
- [ ] Настроена блокировка удалённого Terraform state.
- [x] Настроен Terraform pipeline для каждого коммита в main.
- [x] Настроены сборка и push образа приложения при каждом коммите.
- [x] Настроен деплой версии приложения при создании Git-тега.
- [ ] Подготовлена полная инструкция воспроизведения стенда.
- [ ] Подготовлены ссылки и материалы для сдачи.

## Структура

- terraform/bootstrap — сервисный аккаунт, IAM-роли, S3-ключ и бакет.
- terraform/infrastructure — VPC, подсети, виртуальные машины и группы безопасности.
- ansible — версия Kubespray, inventory и параметры Kubernetes.
- kubernetes — манифесты и настройки Helm для Traefik и мониторинга.
- scripts — генерация inventory, запуск Kubespray и настройка метрик kube-proxy.
- docs — материалы для сдачи.

## Terraform

Использован Terraform 1.9.8 и провайдер yandex-cloud/yandex 0.230.0.

Bootstrap использует локальный state. Его резервная копия хранится
локально в .secrets/bootstrap-backups и не включается в Git.

Основной state хранится в Object Storage:
infrastructure/terraform.tfstate.

Первичное создание bootstrap выполняется с пользовательским IAM-токеном.
Основная инфраструктура управляется сервисным аккаунтом.
Авторизованный ключ сервисного аккаунта создан отдельно через yc CLI.

Файлы terraform.tfvars создаются на основе terraform.tfvars.example.
Секреты, state и сохранённые планы исключены из Git.
Файлы .terraform.lock.hcl включены в репозиторий.

Блокировка удалённого state пока не настроена.
CI-запуски сериализуются через GitHub Actions concurrency.
Ручные запуски основной конфигурации выполняются только при отсутствии
активных CI-запусков. Блокировки между CI и локальным Terraform нет.

## Сеть

| Подсеть | Зона | CIDR |
|---|---|---|
| diplom-a | ru-central1-a | 10.200.10.0/24 |
| diplom-b | ru-central1-b | 10.200.20.0/24 |
| diplom-d | ru-central1-d | 10.200.30.0/24 |

## Проверенный результат

Через Terraform созданы VPC, три подсети, три ВМ и группы безопасности.
После создания ВМ повторный terraform plan показал No changes.
Kubernetes: три узла Ready.
Traefik принимает HTTP-трафик на обоих workers.
Grafana отображает метрики, все 28 настроенных targets Prometheus UP.
Тестовое приложение развёрнуто. CI/CD приложения проверен на релизе v1.0.0. Terraform pipeline настроен: push в main запускает plan и apply.

## Установка Kubernetes

Использован Kubespray v2.32.0. Digest контейнера сохранён
в ansible/kubespray-image.txt.

Версии: Kubernetes 1.36.4, containerd 2.3.5.

scripts/generate-inventory.py принимает JSON из команды
terraform output -json nodes и создаёт inventory.
Ansible подключается по публичным IP, кластер использует внутренние IP.

Установка: ./scripts/run-kubespray.sh.
Перед запуском необходимо сформировать inventory и проверить SSH-ключи узлов.

Для параметров ВМ скопировать
terraform/infrastructure/compute.auto.tfvars.json.example
в compute.auto.tfvars.json в том же каталоге и указать свой admin_cidrs.
ID образа зафиксирован; при воспроизведении проверить его доступность.

Один control plane с etcd и два прерываемых worker.
Сеть подов: Calico VXLAN.
Кластер не обеспечивает отказоустойчивость control plane.

Проверка: docs/kubernetes-check.txt.
Все три узла Ready, системные поды Running.

## Входящий HTTP-трафик

Traefik установлен Helm chart 41.6.0, версия приложения 3.7.13.
Настройки находятся в kubernetes/traefik.

Контроллер работает как DaemonSet на двух worker-узлах.
HTTP поступает на порт 80 публичного IP каждого worker через hostPort.
Service имеет тип ClusterIP. Облачный балансировщик не используется.

IngressClass: traefik.
Маршрут /grafana/ обслуживает Grafana.
Корневой путь / обслуживает тестовое приложение.
docs/traefik-check.txt — первоначальная проверка контроллера
до создания маршрута Grafana.

## Мониторинг

Установлен kube-prometheus-stack, Helm chart 91.8.0.
Grafana: версия приложения 13.2.2, версия зависимого chart 13.2.6.

Компоненты: Prometheus Operator, Prometheus, Grafana,
Alertmanager и kube-state-metrics.
Node-exporter работает на каждом из трёх узлов.

Конфигурация: kubernetes/monitoring.
Grafana: http://158.160.20.63/grafana/
Учётные данные хранятся отдельно от Git.

Prometheus хранит метрики до 2 дней с ограничением retentionSize 5GiB.
Используются локальные PV:
- Prometheus: worker-2, 10Gi.
- Grafana: worker-1, 1Gi.
- Alertmanager: worker-1, 1Gi.

Размеры PV не являются дисковыми квотами.
При недоступности узла использующий его локальный PV компонент
не сможет перенести данные на другой узел.
Удаление ВМ вместе с диском уничтожает эти данные.

Проверено: 28 из 28 настроенных targets UP, три узла Ready,
метрики CPU и памяти доступны, dashboards Grafana отображают данные.
Все три PVC находятся в состоянии Bound.

Подключены метрики etcd, scheduler, controller-manager и kube-proxy.
Сбор выполняется по внутренним адресам кластера.
Внешние уведомления Alertmanager не настроены.

Результаты проверки:
- docs/monitoring-check.txt
- docs/monitoring-metrics-check.txt
- docs/monitoring-targets-check.txt

### Настройки метрик компонентов Kubernetes

Параметры Kubespray сохранены в
ansible/inventory/diplom/group_vars/all/monitoring.yml.

etcd публикует метрики на внутреннем адресе и localhost, порт 2381.
Клиентский API etcd на порту 2379 использует TLS.

kube-proxy публикует метрики на порту 10249.
Доступ к портам метрик извне ограничен группами безопасности Terraform.

Для уже установленного кластера изменение параметра Kubespray
не обновило действующий ConfigMap kube-proxy. Настройка применена:
1. python3 scripts/configure-kube-proxy-metrics.py
2. kubectl -n kube-system rollout restart daemonset/kube-proxy
3. kubectl -n kube-system rollout status daemonset/kube-proxy

Скрипт сохраняет резервную копию ConfigMap в .secrets/kube-proxy-backups
и меняет только metricsBindAddress.

Для HTTPS endpoints scheduler и controller-manager используется
токен Prometheus; проверка серверных сертификатов отключена
в соответствующих ServiceMonitor.

## Container Registry

Через Terraform создан приватный Yandex Container Registry.
Конфигурация: terraform/infrastructure/registry.tf.

Registry ID: crp15t94ei4mots103d9.
Репозиторий образов:
cr.yandex/crp15t94ei4mots103d9/devops-diplom-app.

После создания повторный terraform plan показал No changes.
Образ приложения опубликован и развёрнут в Kubernetes.

## Тестовое приложение

Репозиторий: https://github.com/victoryurochkin/devops-diplom-app

Статическая HTML-страница с собственными Dockerfile и nginx.conf.
Контейнер работает от пользователя nginx и слушает порт 8080.
Локальные тесты проверяют конфигурацию nginx, страницу и /healthz.

Опубликованный образ:
cr.yandex/crp15t94ei4mots103d9/devops-diplom-app:sha-1b7778c23249

Первоначальный деплой закреплён по digest:
sha256:712f10775bde4162e63adec9b3d37a0768c9a230ee9fc10e64d6fd3cc9820ddf

Манифесты: kubernetes/app.
Namespace: diplom-app.
Deployment содержит две реплики на разных worker-узлах.
Service ClusterIP направляет трафик с порта 80 на порт контейнера 8080.
Ingress класса traefik обслуживает путь /.
Путь /grafana/ продолжает обслуживаться мониторингом.

Адреса приложения:
- http://158.160.20.63/
- http://81.26.188.103/

Для скачивания образов Terraform bootstrap создаёт отдельный сервисный
аккаунт с ролью container-registry.images.puller на каталог диплома.
Авторизованный ключ создаётся отдельно через yc CLI и хранится локально
в .secrets/registry-puller-key.json.

После создания namespace команда
python3 scripts/create-registry-pull-secret.py
создаёт или обновляет Secret diplom-app/yc-registry.
Ключ и содержимое Secret не включаются в Git.

Восстановление приложения: scripts/restore-app.sh с digest опубликованного образа в качестве аргумента.
Проверка: docs/app-check.txt.

Первоначальная сборка, публикация и установка выполнены вручную.
Последующие сборка, тестирование, публикация и деплой автоматизированы через GitHub Actions.

## CI/CD приложения

Workflow: .github/workflows/app.yml в репозитории devops-diplom-app.

При push в любую ветку GitHub Actions собирает образ, проверяет
конфигурацию nginx, HTTP-страницу и /healthz, затем публикует образ
с тегом sha-<12 символов коммита>. При ошибке тестов публикация не выполняется.

При push Git-тега создаётся образ с соответствующим Docker-тегом
и OCI label org.opencontainers.image.version.
После успешной сборки и тестов запускается деплой по digest,
ожидание rollout и HTTP-проверки через оба worker.

Сборка выполняется на GitHub-hosted runner ubuntu-24.04.
Деплой выполняется на VM it через self-hosted runner
diplom-app-deploy-it с меткой diplom-deploy.
Runner работает как systemd-служба от пользователя diplom-runner,
без членства в группах sudo и docker.

Для публикации используется Actions Secret YC_REGISTRY_PUSHER_KEY.
Kubeconfig деплоя находится локально на runner:
 /home/diplom-runner/.kube/config
Он использует ServiceAccount diplom-app/app-deployer.
RBAC разрешает изменение Deployment diplom-app и чтение подов
в namespace diplom-app.

Проверенный релиз: v1.0.0.
Образ: cr.yandex/crp15t94ei4mots103d9/devops-diplom-app:v1.0.0
Digest: sha256:e7f328f227f530e7604c6afe04f148bff7543563dd982b61fbd4ad7ca8df4315

Успешный запуск:
https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36405099315

После деплоя: Deployment 2/2, обе реплики Running,
HTTP-проверки приложения прошли.

Конфигурации доступа:
- terraform/bootstrap/registry-pusher.tf
- kubernetes/app/deployer-rbac.yaml
- kubernetes/app/deployer-token.yaml
- scripts/generate-deployer-kubeconfig.py

deployer-token.yaml содержит только описание Secret.
Сам токен создаётся Kubernetes и не включается в Git.
Токен долгоживущий; автоматическая ротация не настроена.

deployment.yaml закрепляет проверенный релиз v1.0.0 для воспроизведения.
Последующие релизы обновляют образ через CD.
Повторное применение этого манифеста вернёт закреплённую в нём версию.

Результаты проверки:
- docs/app-cicd-run.json
- docs/app-release-check.txt
- docs/github-runner-version.txt

## CI/CD инфраструктуры

Workflow: .github/workflows/terraform.yml.

Каждый push в main, включая изменения документации, запускает:
1. Проверку форматирования Terraform.
2. Инициализацию S3 backend и провайдера.
3. Проверку конфигурации.
4. Создание плана.
5. Автоматическое применение сохранённого плана.

Фильтров по путям файлов нет.
Также доступен ручной запуск workflow; apply разрешён только в main.
При ошибке планирования применение не выполняется.

Runner: GitHub-hosted ubuntu-24.04.
Terraform: 1.9.8.
Провайдер: yandex-cloud/yandex 0.230.0, загружается через зеркало Yandex.
Применяется terraform/infrastructure.
Bootstrap выполняется отдельно с пользовательскими правами.

GitHub Actions Secrets инфраструктурного репозитория:
- YC_TERRAFORM_KEY
- TF_STATE_ACCESS_KEY_ID
- TF_STATE_SECRET_ACCESS_KEY
- TF_VARS
- TF_COMPUTE_VARS
- TF_SSH_PUBLIC_KEY

При изменении локальных tfvars нужно обновить соответствующие Secrets.
TF_SSH_PUBLIC_KEY содержит только публичный SSH-ключ.

Проверенный запуск:
https://github.com/victoryurochkin/devops-diplom-yandexcloud/actions/runs/36408675311

Результат: plan — No changes;
apply — 0 added, 0 changed, 0 destroyed.
Это подтверждает запуск apply из CI.
Удаление и пересоздание инфраструктуры этим запуском не проверялись.

Материалы:
- docs/terraform-cicd-run.json
- docs/terraform-cicd-check.txt

### Адреса мониторинга из Terraform

scripts/generate-monitoring-values.py получает JSON из
terraform output -json nodes и создаёт
.secrets/monitoring-runtime.json.

Генерируются:
- Внутренний адрес control plane для etcd, controller-manager и scheduler.
- Публичный URL Grafana на основе адреса worker-1.

Сгенерированный файл исключён из Git.

Установка или обновление Helm-релиза:

    ./scripts/deploy-monitoring.sh

Скрипт получает доступ к S3 state через outputs локального bootstrap,
повторно генерирует адреса, проверяет рендеринг и запускает Helm.
Файл monitoring-runtime.json передаётся после основных values.

Перед запуском необходимы:
- Работающий Kubernetes и доступ через KUBECONFIG или ~/.kube/config.
- SSH-доступ ubuntu к worker-узлам с sudo без пароля.
- Проверенные SSH-ключи узлов в known_hosts.
- Доступ к локальному bootstrap state для получения S3-ключей.
- Существующий Secret grafana-admin либо его локальная резервная копия.

deploy-monitoring.sh автоматически вызывает scripts/prepare-monitoring.py.
Подготавливаются namespace monitoring, каталоги локального хранения,
StorageClass monitoring-local и три PV.

Существующий Secret Grafana сохраняется в
.secrets/grafana-admin-secret.json с правами 0600.
На новом кластере Secret восстанавливается из этого файла.
При несовпадении локальной копии и существующего Secret скрипт
останавливается, сохраняя оба варианта.

SSH-ключ и known_hosts можно задать переменными
DIPLOM_SSH_KEY и DIPLOM_KNOWN_HOSTS.

Повторная подготовка проверена на работающем кластере:
StorageClass и PV unchanged, все три PVC Bound.
Резервная копия Secret содержит только учётные данные;
данные локальных PV в неё не входят.

Проверено 28.09.2026: релиз monitoring обновлён до revision 4,
все поды мониторинга готовы, три PVC Bound.
Адреса в сохранённых Helm values совпадают с Terraform outputs.

Полное восстановление после удаления инфраструктуры
этой проверкой ещё не подтверждено.

## Восстановление приложения и доступа CD

Скрипт: scripts/restore-app.sh.
Единственный аргумент — digest опубликованного образа
в формате sha256: и 64 шестнадцатеричных символа.

Адрес репозитория образов берётся из Terraform output
app_image_repository. Исходный deployment.yaml используется
как шаблон; нужный образ подставляется перед применением.

Скрипт:
- Создаёт namespace и настраивает Secret доступа к Registry.
- Применяет Deployment, Service и Ingress.
- Ожидает завершения rollout и проверяет установленный образ.
- Применяет ServiceAccount, Role, RoleBinding и Secret токена CD.
- Генерирует kubeconfig app-deployer для текущего кластера.
- Устанавливает его пользователю diplom-runner с правами 0600.
- Сохраняет предыдущий kubeconfig runner в файл config.bak-*.
- Проверяет доступ runner к Deployment.

Запуск выполняется на управляющем хосте с установленным runner.
Нужны административный kubeconfig, локальный bootstrap state,
ключ registry-puller и sudo для установки kubeconfig runner.

После пересоздания инфраструктуры:
1. Установить Kubernetes и обновить административный kubeconfig.
2. Синхронизировать CI Variables через scripts/sync-app-ci-vars.py.
3. Собрать и опубликовать образ в актуальном Registry.
4. Запустить scripts/restore-app.sh с digest этого образа.

Проверено на существующем кластере:
Deployment 2/2, digest сохранён, доступ CD-runner работает.
Отчёт: docs/app-restore-check.txt.

Эта проверка подтверждает повторный запуск скрипта.
Полное восстановление после destroy ещё не проверено.

## Очистка Container Registry при удалении инфраструктуры

В terraform/infrastructure/registry.tf настроен local-exec с when = destroy.
Перед удалением реестра Terraform запускает scripts/cleanup-registry.py,
который удаляет все находящиеся в нём образы, включая релизные.
Очистка также запускается при замене ресурса Registry.

Скрипт проверяет каталог, имя и метки реестра, обрабатывает страницы
списка образов и ожидает завершения операций удаления.
Без флага --delete выполняется только просмотр.

Авторизация: ключ из YC_SERVICE_ACCOUNT_KEY_FILE.
Используется существующий сервисный аккаунт Terraform.
Зависимость SDK закреплена в scripts/registry-tools-requirements.txt.

Подготовка Python-окружения из корня репозитория:

    python3 -m venv .secrets/registry-tools
    .secrets/registry-tools/bin/python -m pip install -r scripts/registry-tools-requirements.txt

GitHub Actions устанавливает зависимость автоматически.
Основная конфигурация запускается через
terraform -chdir=terraform/infrastructure.

При terraform plan и apply без удаления Registry очистка не запускается.
Для штатного destroy блок ресурса вместе с provisioner должен
оставаться в конфигурации до завершения удаления.

Перед пересозданием инфраструктуры нужно остановить публикацию образов
и исключить одновременные локальные и CI-запуски Terraform.
Удаление образов необратимо. При ошибке очистки удаление Registry
останавливается; другие ресурсы к этому моменту могут быть уже удалены.

Проверен режим просмотра через Terraform-аккаунт: получены восемь образов.
Реальное удаление и полное пересоздание этим тестом не проверялись.
