resource "yandex_container_registry" "diplom" {
  folder_id = var.folder_id
  name      = "diplom-registry"

  labels = {
    project    = "devops-diplom"
    managed_by = "terraform"
  }
  provisioner "local-exec" {
    when = destroy

    command = <<-EOT
      cd ../.. || exit 1
      .secrets/registry-tools/bin/python scripts/cleanup-registry.py \
        --registry-id "$REGISTRY_ID" \
        --folder-id "$REGISTRY_FOLDER_ID" \
        --delete
    EOT

    environment = {
      REGISTRY_ID        = self.id
      REGISTRY_FOLDER_ID = self.folder_id
    }
  }
}
