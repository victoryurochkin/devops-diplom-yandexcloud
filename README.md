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
- [ ] Созданы репозиторий приложения, Dockerfile и образ в registry.
- [ ] Тестовое приложение развёрнуто и доступно по HTTP.
- [ ] Настроена блокировка удалённого Terraform state.
- [ ] Настроен Terraform pipeline для каждого коммита в main.
- [ ] Настроены сборка и push образа приложения при каждом коммите.
- [ ] Настроен деплой версии приложения при создании Git-тега.
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
До её настройки Terraform запускается последовательно с одного хоста.

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
Тестовое приложение и CI/CD пока не развёрнуты.

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
Корневой путь / пока возвращает HTTP 404: приложение ещё не развёрнуто.
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

Применение манифестов: kubectl apply -f kubernetes/app/
Проверка: docs/app-check.txt.

Первоначальная сборка, публикация и установка выполнены вручную.
Автоматизация CI/CD пока не настроена.
