# Дипломный проект DevOps — Yandex Cloud

**Виктор Юрочкин** · [Задание](https://github.com/netology-code/devops-diplom-yandexcloud)

Облачная инфраструктура управляется Terraform, Kubernetes устанавливается
Kubespray. GitHub Actions собирает и проверяет приложение, публикует образ
в приватный Registry и развёртывает Git-теги в кластере.

- [Материалы для сдачи](docs/SUBMISSION.md)
- [Воспроизведение и эксплуатация](docs/REPRODUCE.md)
- [Репозиторий приложения](https://github.com/victoryurochkin/devops-diplom-app)
- [Terraform pipeline](https://github.com/victoryurochkin/devops-diplom-yandexcloud/actions/workflows/terraform.yml)
- [CI/CD приложения](https://github.com/victoryurochkin/devops-diplom-app/actions/workflows/app.yml)

## Доступ

| Сервис | Адрес |
|---|---|
| Приложение | http://158.160.31.109/ |
| Приложение через второй worker | http://158.160.228.171/ |
| Grafana | http://158.160.31.109/grafana/ |
| Grafana через второй worker | http://158.160.228.171/grafana/ |

Данные доступа Grafana передаются проверяющему отдельно. Ключей и паролей
в репозитории нет. Registry приватный; скачивание образов требует авторизации.

## Соответствие заданию

| Критерий | Реализация |
|---|---|
| Инфраструктура Terraform и удалённый state | [Bootstrap](terraform/bootstrap): сервисные аккаунты и закрытый версионируемый S3-бакет. [Основная конфигурация](terraform/infrastructure): сеть, три подсети, ВМ, адреса, группы безопасности и Registry |
| Три ВМ и Kubernetes через Ansible | [Kubespray](ansible), [генерация inventory](scripts/generate-inventory.py), [установка](scripts/run-kubespray.sh). Workers прерываемые |
| Тестовое приложение и Dockerfile | [Отдельный репозиторий](https://github.com/victoryurochkin/devops-diplom-app): nginx, статическая страница, тесты образа |
| Мониторинг Kubernetes | [kube-prometheus-stack](kubernetes/monitoring): Prometheus, Grafana, Alertmanager, node-exporter и kube-state-metrics |
| HTTP на порту 80 | [Traefik](kubernetes/traefik) на обоих workers; [Ingress приложения](kubernetes/app/ingress.yaml) и Grafana |
| Terraform CI/CD | [Workflow](.github/workflows/terraform.yml): каждый push в main запускает plan и применение сохранённого плана |
| CI приложения | Каждый push в ветку: сборка, тестирование и публикация образа с тегом sha-коммита |
| CD приложения | Push Git-тега: сборка и публикация соответствующего тега, деплой по digest, rollout и HTTP-проверки |
| Демонстрация и подтверждения | [Скриншоты и результаты](docs/SUBMISSION.md); инструкция создания и удаления в [REPRODUCE.md](docs/REPRODUCE.md) |

## Архитектура

| Узел | Зона | Внутренний IP | Публичный IP | Назначение |
|---|---|---|---|---|
| cp-1 | ru-central1-a | 10.200.10.33 | 51.250.67.37 | Control plane и etcd |
| worker-1 | ru-central1-b | 10.200.20.12 | 158.160.31.109 | Приложение, Traefik, Grafana, Alertmanager |
| worker-2 | ru-central1-d | 10.200.30.3 | 158.160.228.171 | Приложение, Traefik, Prometheus |

ВМ: standard-v3, 2 vCPU, 4 ГБ RAM, гарантированная доля CPU 20%, SSD 30 ГБ.
SSH и Kubernetes API доступны только с admin_cidrs. Порт 80 workers открыт
для проверки. Метрики компонентов собираются по внутренней сети.

Сеть подов — Calico VXLAN, 10.233.64.0/18; сервисы — 10.233.0.0/18.
Приложение содержит две реплики на разных workers. Контейнер nginx работает
без root, слушает 8080; Service направляет на него запросы с порта 80.
Readiness и liveness используют /healthz.

## Версии

| Компонент | Версия / источник |
|---|---|
| Terraform | [1.13.5](.terraform-version) |
| Yandex provider | 0.230.0, закреплён в versions.tf и lock-файлах |
| Kubespray | [v2.32.0, образ по digest](ansible/kubespray-image.txt) |
| Kubernetes / containerd | 1.36.4 / 2.3.5 |
| Traefik Helm chart | [41.6.0](kubernetes/traefik/chart-version.txt) |
| kube-prometheus-stack | [91.8.0](kubernetes/monitoring/chart-version.txt) |
| nginx | Digest в Dockerfile приложения |

## Управление и воспроизведение

Terraform bootstrap хранит state локально; основной state — в S3 с native
lockfile. Все операторы и CI используют одну закреплённую версию Terraform.
CI-запуски выполняются последовательно с очередью. Bootstrap выполняется
отдельно, рабочему Terraform-аккаунту назначены сервисные роли без editor/admin
на весь каталог.

Публичные адреса описаны отдельными ресурсами Terraform и сохраняются при
остановке ВМ. Для существующего стенда используется импорт текущих адресов,
описанный в [инструкции эксплуатации](docs/REPRODUCE.md#перевод-существующего-стенда-на-новые-настройки).

На управляющем хосте it работает diplom-maintenance.timer: проверяет workers
каждые две минуты и запускает остановленные ВМ; обновляет ограниченный токен CD.
Запрашиваемый срок токена — два часа. Kubeconfig runner заменяется атомарно,
административный kubeconfig runner не получает. Хост it должен оставаться включённым.

После создания инфраструктуры скрипт sync-app-ci-vars.py обновляет GitHub Variables
и локальные данные обслуживания. Мониторинг получает адреса из Terraform outputs.
restore-app.sh принимает digest образа в текущем Registry и восстанавливает приложение
и доступ CD. Последовательность всех шагов находится в [REPRODUCE.md](docs/REPRODUCE.md).

## Проверки

[Configuration checks](.github/workflows/checks.yml) выполняет проверку синтаксиса,
тесты безопасного выбора workers и выпуска токенов, Terraform fmt и validate.
Рабочий Terraform workflow выполняет plan/apply только для основной конфигурации.

Проверенный релиз приложения: v1.0.1.

    cr.yandex/crp77uvg5d2tuusdlk1f/devops-diplom-app:v1.0.1

В Deployment используется digest, зафиксированный в [манифесте](kubernetes/app/deployment.yaml).
Манифест задаёт версию для первоначального развёртывания; текущий релиз после CD
проверяется через kubectl. Для восстановления выбирается digest явно.

## Границы учебного стенда

Один control plane; workers прерываемые. Их повторный запуск зависит от наличия
ресурсов Yandex Cloud. Локальные PV привязаны к узлам: Prometheus 10 ГиБ,
Grafana и Alertmanager по 1 ГиБ. Prometheus хранит метрики до двух дней / 5 GiB.
Архивы PV нужны для сохранения данных при удалении ВМ. Внешняя доставка уведомлений
Alertmanager не входит в выбранную конфигурацию.
