resource "yandex_iam_service_account" "registry_pusher" {
  folder_id   = var.folder_id
  name        = "diplom-registry-pusher"
  description = "Publish diploma application images from CI"
}

resource "yandex_resourcemanager_folder_iam_member" "registry_pusher" {
  folder_id = var.folder_id
  role      = "container-registry.images.pusher"
  member    = "serviceAccount:${yandex_iam_service_account.registry_pusher.id}"
}

output "registry_pusher_service_account_id" {
  description = "Service account used by application CI to publish images"
  value       = yandex_iam_service_account.registry_pusher.id
}
