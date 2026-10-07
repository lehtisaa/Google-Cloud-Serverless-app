variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "europe-north1"
}

variable "processor_image" {
  description = "Docker image for the Cloud Run processor service. Deploy a placeholder first if not built."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}
