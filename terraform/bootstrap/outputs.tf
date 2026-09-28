output "terraform_service_account_id" {
  description = "Service account for the main infrastructure"
  value       = yandex_iam_service_account.terraform.id
}

output "state_bucket_name" {
  description = "Bucket for the main Terraform state"
  value       = yandex_storage_bucket.state.bucket
}

output "state_access_key" {
  value     = yandex_iam_service_account_static_access_key.state.access_key
  sensitive = true
}

output "state_secret_key" {
  value     = yandex_iam_service_account_static_access_key.state.secret_key
  sensitive = true
}
