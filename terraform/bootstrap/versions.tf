terraform {
  required_version = "= 1.13.5"

  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "= 0.230.0"
    }
  }
}
