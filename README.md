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
- [ ] Развёрнуты приложение и мониторинг.
- [ ] Настроены CI/CD инфраструктуры и приложения.
- [ ] Подготовлены ссылки и материалы для сдачи.

## Структура

- terraform/bootstrap — сервисный аккаунт, IAM-роли, S3-ключ и бакет.
- terraform/infrastructure — сеть и основная инфраструктура.
- ansible — будущая конфигурация установки Kubernetes.
- kubernetes — будущие манифесты и настройки Helm.
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

Созданы одна VPC и три подсети.
Ресурсы доступны через terraform state list.
Повторный terraform plan: No changes.

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
До создания Ingress-маршрутов запросы возвращают HTTP 404.
Проверка: docs/traefik-check.txt.

## Мониторинг

Установлен kube-prometheus-stack, Helm chart 91.8.0.
Grafana: версия приложения 13.2.2, версия зависимого chart 13.2.6.

Компоненты: Prometheus Operator, Prometheus, Grafana,
Alertmanager, kube-state-metrics и node-exporter на всех трёх узлах.

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

Проверено: 22 из 22 настроенных targets UP, три узла Ready,
метрики CPU и памяти доступны, dashboards Grafana отображают данные.
Все три PVC находятся в состоянии Bound.

Метрики etcd, scheduler, controller-manager и kube-proxy
пока не подключены.
Внешние уведомления Alertmanager не настроены.

Результаты проверки:
- docs/monitoring-check.txt
- docs/monitoring-metrics-check.txt
