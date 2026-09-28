variable "cloud_id" {
  description = "Yandex Cloud ID"
  type        = string
}

variable "folder_id" {
  description = "Dedicated diploma folder ID"
  type        = string
}

variable "subnets" {
  description = "Subnet names, availability zones and IPv4 CIDRs"
  type = map(object({
    zone = string
    cidr = string
  }))
}
