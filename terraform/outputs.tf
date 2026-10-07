output "upload_bucket" {
  value       = google_storage_bucket.upload_bucket.name
  description = "The GCS bucket for document uploads"
}

output "cloud_run_service_url" {
  value       = google_cloud_run_v2_service.processor.uri
  description = "The Cloud Run service URL"
}

output "bigquery_dataset" {
  value       = google_bigquery_dataset.document_metadata.dataset_id
  description = "The BigQuery dataset for metadata"
}
