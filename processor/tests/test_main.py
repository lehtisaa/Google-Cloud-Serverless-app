import pytest
import json
from unittest.mock import patch, MagicMock
from main import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@patch('main.write_to_bigquery')
@patch('main.get_storage_client')
def test_process_document_success(mock_get_storage, mock_write_to_bigquery, client):
    # Mock GCS Client
    mock_storage_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    
    # Simulate a file download of an arbitrary text document
    mock_blob.download_as_bytes.return_value = b"This is a test document with exactly nine words here."
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket
    mock_get_storage.return_value = mock_storage_client

    # Simulate CloudEvent payload from Eventarc
    headers = {
        "ce-id": "mock-event-id",
        "ce-source": "//storage.googleapis.com/projects/_/buckets/test-bucket",
        "ce-specversion": "1.0",
        "ce-type": "google.cloud.storage.object.v1.finalized",
        "Content-Type": "application/json"
    }
    
    data = {
        "bucket": "test-bucket",
        "name": "sample_upload.txt"
    }

    # Execute with mocked environment variables
    with patch.dict('os.environ', {'PROJECT_ID': 'test-project', 'BQ_DATASET': 'test_dataset', 'BQ_TABLE': 'test_table'}):
        response = client.post('/', headers=headers, data=json.dumps(data))

    # Assertions
    assert response.status_code == 200
    assert response.data == b"Success"
    
    # Verify GCS was called to download the specific file
    mock_storage_client.bucket.assert_called_with("test-bucket")
    mock_bucket.blob.assert_called_with("sample_upload.txt")
    mock_blob.download_as_bytes.assert_called_once()

    # Verify BigQuery writer was called with simulated metadata
    mock_write_to_bigquery.assert_called_once()
    call_args = mock_write_to_bigquery.call_args[1]
    
    assert call_args['project_id'] == 'test-project'
    assert call_args['dataset_id'] == 'test_dataset'
    assert call_args['table_id'] == 'test_table'
    assert call_args['file_name'] == 'sample_upload.txt'
    assert call_args['word_count'] == 9
    assert call_args['file_extension'] == 'txt'
    assert len(call_args['tags']) > 0  # Random tags were generated
