import os
import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class ReplitObjectStore:
    """
    Replit Object Store integration for temporary file storage during processing.
    Uses S3-compatible API with automatic cleanup.
    """
    
    def __init__(self):
        self.bucket_name = "replit-objstore-42af3b1d-2f64-453b-91fd-821709ea91e8"
        self.s3_client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize S3 client with Replit Object Store credentials."""
        try:
            # Replit Object Store uses AWS S3 compatible API
            self.s3_client = boto3.client(
                's3',
                endpoint_url=os.environ.get('REPLIT_OBJECT_STORE_ENDPOINT'),
                aws_access_key_id=os.environ.get('REPLIT_OBJECT_STORE_ACCESS_KEY'),
                aws_secret_access_key=os.environ.get('REPLIT_OBJECT_STORE_SECRET_KEY'),
                region_name='us-east-1'  # Default region for Replit Object Store
            )
            logger.info("Replit Object Store client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Object Store client: {str(e)}")
            self.s3_client = None
    
    def is_available(self):
        """Check if Object Store is available and configured."""
        return self.s3_client is not None
    
    def upload_file(self, file_content, filename, content_type='application/octet-stream'):
        """
        Upload file content to Object Store.
        
        Args:
            file_content (bytes): File content as bytes
            filename (str): Original filename
            content_type (str): MIME type of the file
        
        Returns:
            str: Object key if successful, None if failed
        """
        if not self.is_available():
            logger.error("Object Store not available")
            return None
        
        try:
            # Generate unique key with timestamp and UUID
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            unique_id = str(uuid.uuid4())[:8]
            file_extension = os.path.splitext(filename)[1]
            object_key = f"temp_attachments/{timestamp}_{unique_id}_{filename}"
            
            # Upload file to Object Store
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=file_content,
                ContentType=content_type,
                Metadata={
                    'original_filename': filename,
                    'upload_timestamp': timestamp,
                    'processing_status': 'pending'
                }
            )
            
            logger.info(f"File uploaded to Object Store: {object_key}")
            return object_key
            
        except ClientError as e:
            logger.error(f"Error uploading file to Object Store: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading file: {str(e)}")
            return None
    
    def download_file(self, object_key):
        """
        Download file from Object Store.
        
        Args:
            object_key (str): Object key in the store
        
        Returns:
            bytes: File content if successful, None if failed
        """
        if not self.is_available():
            logger.error("Object Store not available")
            return None
        
        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=object_key
            )
            
            file_content = response['Body'].read()
            logger.info(f"File downloaded from Object Store: {object_key}")
            return file_content
            
        except ClientError as e:
            logger.error(f"Error downloading file from Object Store: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading file: {str(e)}")
            return None
    
    def delete_file(self, object_key):
        """
        Delete file from Object Store.
        
        Args:
            object_key (str): Object key to delete
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_available():
            logger.error("Object Store not available")
            return False
        
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=object_key
            )
            
            logger.info(f"File deleted from Object Store: {object_key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error deleting file from Object Store: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting file: {str(e)}")
            return False
    
    def cleanup_temp_files(self, max_age_hours=24):
        """
        Clean up temporary files older than specified age.
        
        Args:
            max_age_hours (int): Maximum age in hours before cleanup
        
        Returns:
            int: Number of files cleaned up
        """
        if not self.is_available():
            logger.error("Object Store not available")
            return 0
        
        try:
            # List all objects in temp_attachments folder
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix='temp_attachments/'
            )
            
            if 'Contents' not in response:
                logger.info("No temporary files found for cleanup")
                return 0
            
            cleanup_count = 0
            current_time = datetime.utcnow()
            
            for obj in response['Contents']:
                # Check if file is older than max_age_hours
                last_modified = obj['LastModified'].replace(tzinfo=None)
                age_hours = (current_time - last_modified).total_seconds() / 3600
                
                if age_hours > max_age_hours:
                    if self.delete_file(obj['Key']):
                        cleanup_count += 1
            
            logger.info(f"Cleaned up {cleanup_count} temporary files")
            return cleanup_count
            
        except ClientError as e:
            logger.error(f"Error during cleanup: {str(e)}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error during cleanup: {str(e)}")
            return 0

# Global instance
object_store = ReplitObjectStore()