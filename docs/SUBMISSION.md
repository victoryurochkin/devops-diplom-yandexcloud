# Материалы для сдачи диплома DevOps

**Автор: Виктор Юрочкин**

## Репозитории и критерии

| Требование | Материалы |
|---|---|
| Terraform, сервисный аккаунт, S3 backend | [Bootstrap](../terraform/bootstrap), [инфраструктура](../terraform/infrastructure) |
| Подсети в разных зонах, три ВМ, прерываемые workers | [Сеть](../terraform/infrastructure/network.tf), [ВМ](../terraform/infrastructure/compute.tf), [параметры](../terraform/infrastructure/compute-variables.tf) |
| Kubernetes через Ansible | [Kubespray](../ansible), [inventory](../scripts/generate-inventory.py), [установка](../scripts/run-kubespray.sh) |
| Приложение, собственный Dockerfile, опубликованный образ | [Репозиторий приложения](https://github.com/victoryurochkin/devops-diplom-app), образ указан ниже |
| Prometheus, Grafana, Alertmanager, node-exporter | [Настройки мониторинга](../kubernetes/monitoring), [установка](../scripts/deploy-monitoring.sh) |
| HTTP на порту 80 | [Traefik](../kubernetes/traefik), [манифесты приложения](../kubernetes/app) |
| Terraform pipeline при push в main | [Workflow](../.github/workflows/terraform.yml), [GitHub Actions](https://github.com/victoryurochkin/devops-diplom-yandexcloud/actions/workflows/terraform.yml) |
| Сборка и тесты при коммите, деплой Git-тега | [Workflow приложения](https://github.com/victoryurochkin/devops-diplom-app/blob/main/.github/workflows/app.yml) |
| Воспроизведение, destroy/apply | [Пошаговая инструкция](REPRODUCE.md) |

Выбран self-hosted Kubernetes: один control plane и два прерываемых worker
в трёх зонах. Оба репозитория находятся на GitHub. Интерфейс CI/CD — GitHub Actions.

## Доступ

| Сервис | URL |
|---|---|
| Приложение | http://158.160.31.109/ |
| Приложение через второй worker | http://158.160.228.171/ |
| Grafana | http://158.160.31.109/grafana/ |

Данные доступа Grafana передаются проверяющему в закрытой форме сдачи.

Образ релиза v1.0.2:

    cr.yandex/crp77uvg5d2tuusdlk1f/devops-diplom-app:v1.0.2

Digest:

    sha256:0ffb78eac3a82faf5fdf93c697aa321e3bd921020a58a1ad918778060c4e2eab

Registry приватный; скачивание требует авторизации. Страница приложения публичная.

## Подтверждения

- [Terraform plan/apply в main](https://github.com/victoryurochkin/devops-diplom-yandexcloud/actions/runs/36449731034).
- [Сборка, тесты и публикация приложения при push](https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36448981647).
- [Релиз v1.0.2: публикация и автоматический деплой](https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36449846882).
- [Мониторинг: 28/28 targets UP](checks/monitoring.txt).
- [Deployment 2/2 и HTTP-проверки приложения](checks/application.txt).
- [Статические адреса, блокировка state и обновление доступа CD](checks/operations.txt).

### Terraform CI/CD

![Успешные plan и apply](screenshots/01-terraform.png)

### Сборка и публикация образа

![Успешный CI приложения](screenshots/02-app-ci.png)

### Автоматический деплой

![Rollout и HTTP-проверки](screenshots/03-app-cd.png)

### Grafana

![Дашборд Kubernetes с метриками узла](screenshots/04-grafana.png)

### Приложение

![Публичная страница приложения](screenshots/05-application.png)
