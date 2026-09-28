resource "yandex_iam_service_account" "registry_puller" {
  folder_id   = var.folder_id
  name        = "diplom-registry-puller"
  description = "Pull private container images for diploma Kubernetes workloads"
}

resource "yandex_resourcemanager_folder_iam_member" "registry_puller" {
  folder_id = var.folder_id
  role      = "container-registry.images.puller"
  member    = "serviceAccount:${yandex_iam_service_account.registry_puller.id}"
}

output "registry_puller_service_account_id" {
  description = "Service account used to pull application images"
  value       = yandex_iam_service_account.registry_puller.id
}
