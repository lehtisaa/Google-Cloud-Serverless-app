import os
import random
import logging
from datetime import datetime
from flask import Flask, request
from cloudevents.http import from_http
import google.cloud.logging
from google.cloud import storage
from google.cloud import bigquery_storage_v1
from google.cloud.bigquery_storage_v1 import types
from google.protobuf import descriptor_pb2

# Setup Cloud Logging (wires Python standard logging to Cloud Logging JSON payload)
log_client = google.cloud.logging.Client()
log_client.setup_logging()
logger = logging.getLogger("doc-processor")

# Lazy import for the compiled protobuf to gracefully allow local unit tests to pass
# without requiring `grpcio-tools` compilation beforehand.
try:
    import metadata_pb2
except ImportError:
    metadata_pb2 = None
    logger.warning("metadata_pb2 not found. Compile it using protoc for production use.")

app = Flask(__name__)

# Pre-defined random tags for simulated OCR
PREDEFINED_TAGS = ["invoice", "receipt", "confidential", "report", "draft", "scanned", "urgent"]

# Global clients to reuse across invocations (best practice for Cloud Run)
storage_client = None
bq_storage_client = None

def get_storage_client():
    global storage_client
    if not storage_client:
        storage_client = storage.Client()
    return storage_client

def get_bq_storage_client():
    global bq_storage_client
    if not bq_storage_client:
        bq_storage_client = bigquery_storage_v1.BigQueryWriteClient()
    return bq_storage_client

@app.route('/', methods=['POST'])
def process_document():
    try:
        # 1. Parse CloudEvent payload sent by Eventarc
        event = from_http(request.headers, request.get_data())
        data = event.data

        bucket_name = data.get('bucket')
        file_name = data.get('name')

        if not bucket_name or not file_name:
            logger.warning("Invalid event payload: missing 'bucket' or 'name'.")
            return "Bad Request", 400

        logger.info(f"Triggered processing for gs://{bucket_name}/{file_name}")

        # 2. Read file bytes from GCS
        s_client = get_storage_client()
        bucket = s_client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        
        try:
            content = blob.download_as_bytes()
        except Exception as e:
            logger.error(f"Failed to download {file_name} from {bucket_name}: {e}")
            return "File Not Found or Access Denied", 404

        # 3. Simulate OCR Processing
        try:
            # Decode ignoring errors to get a rough word count
            text_content = content.decode('utf-8', errors='ignore')
            word_count = len(text_content.split())
        except Exception as e:
            logger.warning(f"Text decoding failed, defaulting word count to 0: {e}")
            word_count = 0

        file_extension = os.path.splitext(file_name)[1].lower().replace('.', '')
        tags = random.sample(PREDEFINED_TAGS, k=random.randint(1, 3))
        upload_date = datetime.utcnow().isoformat()

        logger.info(f"Simulated OCR complete. Word count: {word_count}, Tags: {tags}")

        # 4. Stream Results to BigQuery via Storage Write API
        project_id = os.environ.get("PROJECT_ID")
        dataset_id = os.environ.get("BQ_DATASET")
        table_id = os.environ.get("BQ_TABLE")

        if not all([project_id, dataset_id, table_id]):
            logger.error("Missing BigQuery environment variables (PROJECT_ID, BQ_DATASET, BQ_TABLE).")
            return "Server Configuration Error", 500

        write_to_bigquery(
            project_id=project_id,
            dataset_id=dataset_id,
            table_id=table_id,
            file_name=file_name,
            upload_date=upload_date,
            tags=tags,
            word_count=word_count,
            file_extension=file_extension
        )

        logger.info(f"Successfully wrote metadata for {file_name} to BigQuery.")
        return "Success", 200

    except Exception as e:
        logger.error(f"Error processing document: {str(e)}", exc_info=True)
        return "Internal Server Error", 500


def write_to_bigquery(project_id, dataset_id, table_id, file_name, upload_date, tags, word_count, file_extension):
    """
    Writes a single row to BigQuery using the low-latency BigQuery Storage Write API.
    Requires protobuf compilation of metadata.proto.
    """
    if not metadata_pb2:
        raise RuntimeError("metadata_pb2 is not available. Ensure you have compiled metadata.proto.")

    bq_client = get_bq_storage_client()
    
    # The default stream path for append rows
    parent = bq_client.table_path(project_id, dataset_id, table_id)
    write_stream_path = f"{parent}/_default"

    # Construct the Protocol Buffer Row
    row = metadata_pb2.DocumentMetadata()
    row.filename = file_name
    row.upload_date = upload_date
    row.tags.extend(tags)
    row.word_count = word_count
    if file_extension:
        row.file_extension = file_extension

    # Get proto descriptor to describe the schema to BigQuery
    proto_descriptor = descriptor_pb2.DescriptorProto()
    metadata_pb2.DocumentMetadata.DESCRIPTOR.CopyToProto(proto_descriptor)

    # Wrap the schema inside a ProtoSchema
    proto_data = types.AppendRowsRequest.ProtoData()
    proto_data.writer_schema = types.ProtoSchema(proto_descriptor=proto_descriptor)

    # Wrap the serialized row inside ProtoRows
    proto_rows = types.ProtoRows()
    proto_rows.serialized_rows.append(row.SerializeToString())
    proto_data.rows = proto_rows

    # Create the append request
    request_msg = types.AppendRowsRequest(
        write_stream=write_stream_path,
        proto_rows=proto_data
    )

    # BigQuery write_client.append_rows expects an iterator/generator of requests
    def request_generator():
        yield request_msg

    responses = bq_client.append_rows(requests=request_generator())

    # Iterate over responses to check for insertion errors
    for response in responses:
        if response.error.code:
            raise Exception(f"BigQuery Write API Error: {response.error.message}")

if __name__ == "__main__":
    # For local development
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
