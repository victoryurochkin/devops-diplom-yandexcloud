variable "ubuntu_image_id" {
  description = "Pinned Ubuntu 24.04 image ID"
  type        = string
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidrs" {
  description = "Allowed source networks for SSH and Kubernetes API"
  type        = list(string)
}

variable "nodes" {
  type = map(object({
    subnet        = string
    cores         = number
    memory        = number
    core_fraction = number
    disk_size     = number
    preemptible   = bool
    worker        = bool
  }))

  default = {
    cp-1 = {
      subnet        = "a"
      cores         = 2
      memory        = 4
      core_fraction = 20
      disk_size     = 30
      preemptible   = false
      worker        = false
    }
    worker-1 = {
      subnet        = "b"
      cores         = 2
      memory        = 4
      core_fraction = 20
      disk_size     = 30
      preemptible   = true
      worker        = true
    }
    worker-2 = {
      subnet        = "d"
      cores         = 2
      memory        = 4
      core_fraction = 20
      disk_size     = 30
      preemptible   = true
      worker        = true
    }
  }
}
