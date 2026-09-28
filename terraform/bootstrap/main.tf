resource "yandex_iam_service_account" "terraform" {
  folder_id   = var.folder_id
  name        = "diplom-terraform"
  description = "Terraform infrastructure management for DevOps diploma"
}

resource "yandex_resourcemanager_folder_iam_member" "terraform" {
  for_each = toset([
    "compute.editor",
    "vpc.publicAdmin",
    "vpc.securityGroups.admin",
    "vpc.privateAdmin",
    "container-registry.editor",
    "storage.editor",
  ])

  folder_id = var.folder_id
  role      = each.value
  member    = "serviceAccount:${yandex_iam_service_account.terraform.id}"
}

resource "yandex_iam_service_account_static_access_key" "state" {
  service_account_id = yandex_iam_service_account.terraform.id
  description        = "S3 credentials for Terraform state"
}

# Bootstrap uses the operator's IAM token to create and configure the bucket.
resource "yandex_storage_bucket" "state" {
  folder_id     = var.folder_id
  bucket        = var.state_bucket_name
  force_destroy = false

  versioning {
    enabled = true
  }

  anonymous_access_flags {
    read        = false
    list        = false
    config_read = false
  }

  lifecycle {
    prevent_destroy = true
  }
}
