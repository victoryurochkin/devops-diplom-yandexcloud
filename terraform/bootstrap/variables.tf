variable "cloud_id" {
  description = "Yandex Cloud ID"
  type        = string
}

variable "folder_id" {
  description = "Dedicated diploma folder ID"
  type        = string
}

variable "state_bucket_name" {
  description = "Globally unique Terraform state bucket name"
  type        = string
}
