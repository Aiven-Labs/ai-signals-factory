#!/usr/bin/env bash
# S3-compatible blob store for Langfuse on a Nevia computer (SeaweedFS).
# MinIO is not used: its binary downloads were withdrawn.
set -euo pipefail
nevia secrets BLOB_ROOT_USER --file - <<<"$(openssl rand -hex 16)"
nevia secrets BLOB_ROOT_PASSWORD --file - <<<"$(openssl rand -hex 24)"
nevia new blob -p 443:9000 \
  -e 'MINIO_ROOT_USER={{secrets.BLOB_ROOT_USER}}' \
  -e 'MINIO_ROOT_PASSWORD={{secrets.BLOB_ROOT_PASSWORD}}' --wait
nevia exec blob --entrypoint '' -- sh -c '
  cd ~ && curl -fsSL -o weed.tgz https://github.com/seaweedfs/seaweedfs/releases/latest/download/linux_amd64.tar.gz &&
  tar -xzf weed.tgz && rm weed.tgz && mkdir -p data &&
  printf "{\"identities\":[{\"name\":\"factory\",\"credentials\":[{\"accessKey\":\"%s\",\"secretKey\":\"%s\"}],\"actions\":[\"Admin\",\"Read\",\"Write\",\"List\",\"Tagging\"]}]}" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" > s3.json &&
  chmod 600 s3.json &&
  (setsid nohup ./weed server -dir=$HOME/data -ip.bind=0.0.0.0 -s3 -s3.port=9000 -s3.config=$HOME/s3.json -master.volumeSizeLimitMB=1024 -volume.max=20 > weed.log 2>&1 &)'
# Open question: does the server survive idle sleep and restart? Test before relying on it.
