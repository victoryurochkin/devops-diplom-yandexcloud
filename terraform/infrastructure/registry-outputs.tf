output "registry_id" {
  description = "Yandex Container Registry ID"
  value       = yandex_container_registry.diplom.id
}

output "app_image_repository" {
  description = "Docker image repository for the diploma application"
  value       = "cr.yandex/${yandex_container_registry.diplom.id}/devops-diplom-app"
}
