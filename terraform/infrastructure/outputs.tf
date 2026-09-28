output "network_id" {
  value = yandex_vpc_network.diplom.id
}

output "subnets" {
  value = {
    for name, subnet in yandex_vpc_subnet.diplom : name => {
      id   = subnet.id
      zone = subnet.zone
      cidr = subnet.v4_cidr_blocks
    }
  }
}
