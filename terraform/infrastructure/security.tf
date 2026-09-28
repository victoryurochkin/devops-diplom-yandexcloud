resource "yandex_vpc_security_group" "cluster" {
  name       = "diplom-cluster"
  folder_id  = var.folder_id
  network_id = yandex_vpc_network.diplom.id

  ingress {
    description       = "Internal cluster communication"
    protocol          = "ANY"
    predefined_target = "self_security_group"
  }

  ingress {
    description    = "SSH from management host"
    protocol       = "TCP"
    port           = 22
    v4_cidr_blocks = var.admin_cidrs
  }

  ingress {
    description    = "Kubernetes API from management host"
    protocol       = "TCP"
    port           = 6443
    v4_cidr_blocks = var.admin_cidrs
  }

  egress {
    description    = "Outbound access"
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "web" {
  name       = "diplom-web"
  folder_id  = var.folder_id
  network_id = yandex_vpc_network.diplom.id

  ingress {
    description    = "Public HTTP"
    protocol       = "TCP"
    port           = 80
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}
