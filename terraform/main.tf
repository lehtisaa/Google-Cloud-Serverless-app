data "google_project" "project" {}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# --- GCS Bucket for Uploads ---
resource "google_storage_bucket" "upload_bucket" {
  name                        = "doc-uploads-${var.project_id}-${random_id.bucket_suffix.hex}"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
}

# --- BigQuery Dataset and Table ---
resource "google_bigquery_dataset" "document_metadata" {
  dataset_id  = "document_processing"
  location    = var.region
  description = "Dataset for processed document metadata"
}

resource "google_bigquery_table" "metadata" {
  dataset_id = google_bigquery_dataset.document_metadata.dataset_id
  table_id   = "metadata"

  schema = <<EOF
[
  {"name": "filename", "type": "STRING", "mode": "REQUIRED"},
  {"name": "upload_date", "type": "STRING", "mode": "REQUIRED"},
  {"name": "tags", "type": "STRING", "mode": "REPEATED"},
  {"name": "word_count", "type": "INTEGER", "mode": "REQUIRED"},
  {"name": "file_extension", "type": "STRING", "mode": "NULLABLE"}
]
EOF
}

# --- IAM for Cloud Run ---
resource "google_service_account" "processor_sa" {
  account_id   = "doc-processor-sa"
  display_name = "Document Processor Cloud Run Service Account"
}

resource "google_project_iam_member" "processor_bq_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.processor_sa.email}"
}

resource "google_storage_bucket_iam_member" "processor_storage_viewer" {
  bucket = google_storage_bucket.upload_bucket.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.processor_sa.email}"
}

# Allow Cloud Run to write structured logs to Cloud Logging
resource "google_project_iam_member" "processor_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.processor_sa.email}"
}

# --- Cloud Run Service ---
resource "google_cloud_run_v2_service" "processor" {
  name     = "doc-processor"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY" # Ensure it is only accessible via internal traffic/Eventarc

  template {
    service_account = google_service_account.processor_sa.email
    containers {
      image = var.processor_image
      env {
        name  = "BQ_DATASET"
        value = google_bigquery_dataset.document_metadata.dataset_id
      }
      env {
        name  = "BQ_TABLE"
        value = google_bigquery_table.metadata.table_id
      }
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

# --- Eventarc Setup ---
resource "google_service_account" "eventarc_trigger_sa" {
  account_id   = "eventarc-trigger-sa"
  display_name = "Eventarc Trigger Service Account"
}

resource "google_project_iam_member" "eventarc_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.eventarc_trigger_sa.email}"
}

resource "google_project_iam_member" "eventarc_event_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.eventarc_trigger_sa.email}"
}

# Grant GCS service agent pubsub.publisher role to publish to Eventarc
data "google_storage_project_service_account" "gcs_account" {}

resource "google_project_iam_member" "gcs_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# Grant default Pub/Sub SA Token Creator to support Eventarc
# Often required for Eventarc to manage its underlying Pub/Sub topic
resource "google_project_iam_member" "pubsub_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_eventarc_trigger" "gcs_trigger" {
  name            = "gcs-upload-trigger"
  location        = var.region
  service_account = google_service_account.eventarc_trigger_sa.email

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.upload_bucket.name
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.processor.name
      region  = var.region
    }
  }

  depends_on = [
    google_project_iam_member.gcs_pubsub_publisher,
    google_project_iam_member.pubsub_token_creator
  ]
}
