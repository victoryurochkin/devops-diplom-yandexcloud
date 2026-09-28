resource "yandex_container_registry" "diplom" {
  folder_id = var.folder_id
  name      = "diplom-registry"

  labels = {
    project    = "devops-diplom"
    managed_by = "terraform"
  }
}
