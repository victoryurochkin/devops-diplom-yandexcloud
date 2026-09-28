terraform {
  backend "s3" {
    endpoints = {
      s3 = "https://storage.yandexcloud.net"
    }

    bucket       = "diplom-tfstate-b1g9bdu0ehutc09likpk"
    key          = "infrastructure/terraform.tfstate"
    region       = "ru-central1"
    use_lockfile = true

    skip_region_validation      = true
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
