output "nodes" {
  description = "Addresses for SSH and Ansible inventory"

  value = {
    for name, node in yandex_compute_instance.node : name => {
      id         = node.id
      zone       = node.zone
      private_ip = node.network_interface[0].ip_address
      public_ip  = node.network_interface[0].nat_ip_address
      ssh_user   = "ubuntu"
    }
  }
}
