import io
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

_s3_client = boto3.client("s3", region_name=AWS_REGION)


def upload_fileobj(fileobj, key: str) -> str:
    _s3_client.upload_fileobj(fileobj, S3_BUCKET_NAME, key)
    return f"s3://{S3_BUCKET_NAME}/{key}"


def download_fileobj(key: str) -> io.BytesIO:
    buffer = io.BytesIO()
    _s3_client.download_fileobj(S3_BUCKET_NAME, key, buffer)
    buffer.seek(0)
    return buffer


def delete_prefix(prefix: str) -> None:
    paginator = _s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            _s3_client.delete_objects(Bucket=S3_BUCKET_NAME, Delete={"Objects": keys})


def key_for(business_id, upload_session_id, dataset_type: str) -> str:
    return f"businesses/{business_id}/uploads/{upload_session_id}/{dataset_type}.csv"


def document_key_for(business_id, upload_session_id) -> str:
    """v0.3 document processing -- one photographed receipt/invoice per
    document upload_session. No extension in the key (we don't rely on it
    for anything; the image's mime type is captured separately and passed
    to the vision call). See docs/decisions.md [2026-07-24]."""
    return f"businesses/{business_id}/documents/{upload_session_id}/receipt"
