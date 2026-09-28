resource "yandex_vpc_network" "diplom" {
  folder_id = var.folder_id
  name      = "diplom-network"

  labels = {
    project    = "devops-diplom"
    managed_by = "terraform"
  }
}

resource "yandex_vpc_subnet" "diplom" {
  for_each = var.subnets

  folder_id      = var.folder_id
  name           = "diplom-${each.key}"
  zone           = each.value.zone
  network_id     = yandex_vpc_network.diplom.id
  v4_cidr_blocks = [each.value.cidr]
}
