resource "yandex_vpc_address" "node" {
  for_each = var.nodes

  folder_id = var.folder_id
  name      = "diplom-${each.key}-public"

  external_ipv4_address {
    zone_id = var.subnets[each.value.subnet].zone
  }

  labels = {
    project    = "devops-diplom"
    managed_by = "terraform"
  }
}
