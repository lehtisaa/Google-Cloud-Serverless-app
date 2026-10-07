FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Compile Protocol Buffers
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. metadata.proto

# Run the web service on container startup using gunicorn
ENV PORT 8080
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
