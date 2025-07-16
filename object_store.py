
import os
import logging
import uuid
from datetime import datetime
from replit.object_storage import Client

logger = logging.getLogger(__name__)

class ReplitObjectStore:
    """
    Replit Object Store integration for temporary file storage during processing.
    Uses the official Replit Object Storage SDK.
    """
    
    def __init__(self):
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Replit Object Storage client."""
        try:
            # Create client instance - no parameters needed for Replit Object Storage
            self.client = Client()
            logger.info("Replit Object Store client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Object Store client: {str(e)}")
            self.client = None
    
    def is_available(self):
        """Check if Object Store is available and configured."""
        return self.client is not None
    
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
            
            # Convert bytes to string if needed for upload_from_text
            if isinstance(file_content, bytes):
                try:
                    # Try to decode as text first
                    content_str = file_content.decode('utf-8')
                    self.client.upload_from_text(object_key, content_str)
                except UnicodeDecodeError:
                    # For binary files, use upload_from_bytes if available
                    # If not available, encode as base64
                    import base64
                    content_str = base64.b64encode(file_content).decode('ascii')
                    # Store with metadata indicating it's base64 encoded
                    object_key = f"temp_attachments/{timestamp}_{unique_id}_b64_{filename}"
                    self.client.upload_from_text(object_key, content_str)
            else:
                # Already a string
                self.client.upload_from_text(object_key, file_content)
            
            logger.info(f"File uploaded to Object Store: {object_key}")
            return object_key
            
        except Exception as e:
            logger.error(f"Error uploading file to Object Store: {str(e)}")
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
            content = self.client.download_as_text(object_key)
            
            # Check if this was a base64 encoded file
            if "_b64_" in object_key:
                import base64
                file_content = base64.b64decode(content.encode('ascii'))
            else:
                # Return as bytes
                file_content = content.encode('utf-8')
            
            logger.info(f"File downloaded from Object Store: {object_key}")
            return file_content
            
        except Exception as e:
            logger.error(f"Error downloading file from Object Store: {str(e)}")
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
            self.client.delete(object_key)
            logger.info(f"File deleted from Object Store: {object_key}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file from Object Store: {str(e)}")
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
            # List all objects
            objects = self.client.list()
            
            if not objects:
                logger.info("No files found for cleanup")
                return 0
            
            cleanup_count = 0
            current_time = datetime.utcnow()
            
            for obj in objects:
                # Check if it's a temp file
                if obj.name.startswith('temp_attachments/'):
                    # Extract timestamp from filename
                    try:
                        # Format: temp_attachments/YYYYMMDD_HHMMSS_uniqueid_filename
                        parts = obj.name.split('/')
                        if len(parts) >= 2:
                            filename_parts = parts[1].split('_')
                            if len(filename_parts) >= 2:
                                timestamp_str = f"{filename_parts[0]}_{filename_parts[1]}"
                                file_time = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                                age_hours = (current_time - file_time).total_seconds() / 3600
                                
                                if age_hours > max_age_hours:
                                    if self.delete_file(obj.name):
                                        cleanup_count += 1
                    except Exception as e:
                        logger.warning(f"Could not parse timestamp for {obj.name}: {str(e)}")
            
            logger.info(f"Cleaned up {cleanup_count} temporary files")
            return cleanup_count
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            return 0

# Global instance
object_store = ReplitObjectStore()
