import logging
try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from django.conf import settings

logger = logging.getLogger(__name__)

class S3StorageClient:
    """
    S3-compatible Object Storage Client for MinIO / AWS S3.
    Provides a modular storage layer so PostgreSQL stores metadata/object_keys,
    and actual file binaries reside in local MinIO or production AWS S3.
    """

    def __init__(self):
        self.endpoint_url = getattr(settings, 'MINIO_ENDPOINT_URL', 'http://localhost:9000')
        self.external_endpoint_url = getattr(settings, 'MINIO_EXTERNAL_ENDPOINT_URL', self.endpoint_url)
        self.access_key = getattr(settings, 'MINIO_ACCESS_KEY', 'minioadmin')
        self.secret_key = getattr(settings, 'MINIO_SECRET_KEY', 'minioadmin')
        self.bucket_name = getattr(settings, 'MINIO_STORAGE_BUCKET_NAME', 'cubixskill-media')
        self.region_name = getattr(settings, 'MINIO_REGION_NAME', 'us-east-1')
        self.use_ssl = getattr(settings, 'MINIO_USE_SSL', False)

        if BOTO3_AVAILABLE:
            # Build boto3 client for internal communication
            self.client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region_name,
                use_ssl=self.use_ssl,
                config=Config(signature_version='s3v4')
            )

            # Build client for external presigned URL generation if external endpoint differs
            if self.external_endpoint_url != self.endpoint_url:
                self.ext_client = boto3.client(
                    's3',
                    endpoint_url=self.external_endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name=self.region_name,
                    use_ssl=self.use_ssl,
                    config=Config(signature_version='s3v4')
                )
            else:
                self.ext_client = self.client
        else:
            self.client = None
            self.ext_client = None

    def ensure_bucket_exists(self) -> bool:
        """
        Check if the target bucket exists, and create it if missing.
        """
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code in ('404', 'NoSuchBucket'):
                try:
                    self.client.create_bucket(Bucket=self.bucket_name)
                    logger.info(f"Created MinIO bucket '{self.bucket_name}' successfully.")
                    return True
                except Exception as create_err:
                    logger.error(f"Failed to create bucket '{self.bucket_name}': {create_err}")
                    return False
            logger.error(f"Bucket check failed: {e}")
            return False

    def upload_file(self, file_obj, object_key: str, content_type: str = 'application/octet-stream') -> str:
        """
        Directly upload file bytes/stream to MinIO/S3.
        """
        self.ensure_bucket_exists()
        extra_args = {'ContentType': content_type}
        
        if hasattr(file_obj, 'read'):
            self.client.upload_fileobj(file_obj, self.bucket_name, object_key, ExtraArgs=extra_args)
        elif isinstance(file_obj, (bytes, bytearray)):
            self.client.put_object(Bucket=self.bucket_name, Key=object_key, Body=file_obj, ContentType=content_type)
        else:
            raise ValueError("Unsupported file_obj type for upload.")

        return object_key

    def generate_presigned_upload_url(self, object_key: str, mime_type: str = 'application/octet-stream', expires_in: int = 900) -> str:
        """
        Generate pre-signed PUT URL for client-side direct upload to MinIO/S3.
        """
        self.ensure_bucket_exists()
        params = {
            'Bucket': self.bucket_name,
            'Key': object_key,
            'ContentType': mime_type
        }
        url = self.ext_client.generate_presigned_url(
            ClientMethod='put_object',
            Params=params,
            ExpiresIn=expires_in
        )
        return url

    def generate_presigned_download_url(self, object_key: str, expires_in: int = 3600) -> str:
        """
        Generate pre-signed GET URL for secure media access.
        """
        params = {
            'Bucket': self.bucket_name,
            'Key': object_key
        }
        url = self.ext_client.generate_presigned_url(
            ClientMethod='get_object',
            Params=params,
            ExpiresIn=expires_in
        )
        return url

    def get_public_url(self, object_key: str) -> str:
        """
        Construct direct URL for bucket objects (if public).
        """
        base_endpoint = self.external_endpoint_url.rstrip('/')
        return f"{base_endpoint}/{self.bucket_name}/{object_key.lstrip('/')}"

    def delete_file(self, object_key: str) -> bool:
        """
        Safely delete an object from MinIO/S3.
        """
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=object_key)
            logger.info(f"Deleted object '{object_key}' from MinIO bucket '{self.bucket_name}'.")
            return True
        except ClientError as e:
            logger.error(f"Error deleting object '{object_key}' from MinIO: {e}")
            return False

    def file_exists(self, object_key: str) -> bool:
        """
        Check if an object exists in MinIO/S3.
        """
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError:
            return False

# Global storage client instance
storage_client = S3StorageClient()
