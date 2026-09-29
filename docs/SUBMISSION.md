# Материалы для сдачи диплома DevOps

**Автор: Виктор Юрочкин**

Диплом принят. Стенд отключён 29.09.2026; ниже сохранены подтверждения выполненных
критериев. Облачные ресурсы удалены, прежние IP больше не принадлежат стенду.
[Повторное развёртывание](DECOMMISSION.md#повторное-развёртывание).

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

## Проверенный релиз

Образ релиза v1.0.2:

    cr.yandex/crp77uvg5d2tuusdlk1f/devops-diplom-app:v1.0.2

Digest:

    sha256:0ffb78eac3a82faf5fdf93c697aa321e3bd921020a58a1ad918778060c4e2eab

Registry удалён при завершении работы. Образ с указанным digest сохранён
в закрытой резервной копии; публичные подтверждения находятся ниже.

## Подтверждения

- [Terraform plan/apply при push в main](https://github.com/victoryurochkin/devops-diplom-yandexcloud/actions/runs/36450662536).
- [Сборка, тесты и публикация приложения при push](https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36450750256).
- [Релиз v1.0.2: публикация и автоматический деплой](https://github.com/victoryurochkin/devops-diplom-app/actions/runs/36449846882).
- [Terraform: No changes, apply без изменений ресурсов](checks/terraform.txt).
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
