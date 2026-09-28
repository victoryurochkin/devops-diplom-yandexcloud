resource "yandex_compute_instance" "node" {
  for_each = var.nodes

  folder_id   = var.folder_id
  name        = "diplom-${each.key}"
  hostname    = each.key
  zone        = var.subnets[each.value.subnet].zone
  platform_id = "standard-v3"

  allow_stopping_for_update = true

  labels = {
    project    = "devops-diplom"
    managed_by = "terraform"
    role       = each.value.worker ? "worker" : "control-plane"
  }

  resources {
    cores         = each.value.cores
    memory        = each.value.memory
    core_fraction = each.value.core_fraction
  }

  boot_disk {
    auto_delete = true

    initialize_params {
      name     = "diplom-${each.key}-boot"
      image_id = var.ubuntu_image_id
      type     = "network-ssd"
      size     = each.value.disk_size
    }
  }

  scheduling_policy {
    preemptible = each.value.preemptible
  }

  network_interface {
    subnet_id = yandex_vpc_subnet.diplom[each.value.subnet].id
    nat       = true

    security_group_ids = concat(
      [yandex_vpc_security_group.cluster.id],
      each.value.worker ? [yandex_vpc_security_group.web.id] : []
    )
  }

  metadata = {
    ssh-keys = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
  }
}
