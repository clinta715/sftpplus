from sftp_creds import get_credentials, set_credentials
from sftp_downloadworkerclass import (
    create_response_queue, delete_response_queue,
    check_response_queue, add_sftp_job, ResponseQueueContext
)
from icecream import ic


class FileOperationsMixin:
    """Mixin class providing file operation functionality.
    
    This class handles:
    - Directory operations (mkdir, rmdir)
    - File operations (remove, rename)
    - Directory listing
    - File existence and type checks
    """

    def sftp_mkdir(self, remote_path):
        """Create a remote directory.
        
        Args:
            remote_path: The path of the directory to create
            
        Returns:
            True if successful, False otherwise
        """
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                remote_path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'mkdir', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=30)
                
                if result and result.get('status') == 'success':
                    self.message_signal.emit(f"Directory created: {remote_path}")
                    self.get_files(force_refresh=True)
                    return True
                else:
                    error = result.get('error', 'Unknown error') if result else 'Timeout'
                    self.message_signal.emit(f"Failed to create directory: {error}")
                    return False
                    
        except Exception as e:
            self.message_signal.emit(f"Error creating directory: {e}")
            return False

    def sftp_rmdir(self, remote_path):
        """Remove a remote directory.
        
        Args:
            remote_path: The path of the directory to remove
            
        Returns:
            True if successful, False otherwise
        """
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                remote_path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'rmdir', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=30)
                
                if result and result.get('status') == 'success':
                    self.message_signal.emit(f"Directory removed: {remote_path}")
                    self.get_files(force_refresh=True)
                    return True
                else:
                    error = result.get('error', 'Unknown error') if result else 'Timeout'
                    self.message_signal.emit(f"Failed to remove directory: {error}")
                    return False
                    
        except Exception as e:
            self.message_signal.emit(f"Error removing directory: {e}")
            return False

    def sftp_remove(self, remote_path):
        """Remove a remote file.
        
        Args:
            remote_path: The path of the file to remove
            
        Returns:
            True if successful, False otherwise
        """
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                remote_path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'remove', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=30)
                
                if result and result.get('status') == 'success':
                    self.message_signal.emit(f"File removed: {remote_path}")
                    self.get_files(force_refresh=True)
                    return True
                else:
                    error = result.get('error', 'Unknown error') if result else 'Timeout'
                    self.message_signal.emit(f"Failed to remove file: {error}")
                    return False
                    
        except Exception as e:
            self.message_signal.emit(f"Error removing file: {e}")
            return False

    def sftp_rename(self, remote_path, new_name):
        """Rename a remote file or directory.
        
        Args:
            remote_path: The current path
            new_name: The new name (not full path)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            directory, filename = self.split_path(remote_path)
            new_path = f"{directory}/{new_name}".replace('//', '/')
            
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                remote_path, True, new_path, True,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'rename', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=30)
                
                if result and result.get('status') == 'success':
                    self.message_signal.emit(f"Renamed to: {new_name}")
                    self.get_files(force_refresh=True)
                    return True
                else:
                    error = result.get('error', 'Unknown error') if result else 'Timeout'
                    self.message_signal.emit(f"Failed to rename: {error}")
                    return False
                    
        except Exception as e:
            self.message_signal.emit(f"Error renaming: {e}")
            return False

    def sftp_listdir(self, remote_path):
        """List files in a remote directory.
        
        Args:
            remote_path: The path to list
            
        Returns:
            List of filenames
        """
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                remote_path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'list', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=30)
                
                if result and result.get('status') == 'success':
                    return result.get('files', [])
                else:
                    return []
                    
        except Exception as e:
            ic(f"Error listing directory: {e}")
            return []

    def sftp_listdir_attr(self, remote_path):
        """List files in a remote directory with attributes.
        
        Args:
            remote_path: The path to list
            
        Returns:
            List of file attributes
        """
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                remote_path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'listattr', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=30)
                
                if result and result.get('status') == 'success':
                    return result.get('files', [])
                else:
                    return []
                    
        except Exception as e:
            ic(f"Error listing directory with attributes: {e}")
            return []

    def sftp_exists(self, path):
        """Check if a remote path exists.
        
        Args:
            path: The path to check
            
        Returns:
            True if path exists, False otherwise
        """
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'exists', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=10)
                
                if result and result.get('status') == 'success':
                    return result.get('exists', False)
                return False
                
        except Exception as e:
            return False

    def is_remote_directory(self, partial_remote_path):
        """Check if a remote path is a directory.
        
        Args:
            partial_remote_path: The path to check
            
        Returns:
            True if path is a directory, False otherwise
        """
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '/')
        full_path = self.get_normalized_remote_path(current_remote_directory, partial_remote_path)
        
        try:
            job_id = create_random_integer()
            create_response_queue(job_id)
            
            add_sftp_job(
                full_path, True, '', False,
                self.init_hostname, self.init_username,
                self.init_password, self.init_port,
                'isdir', job_id, self.init_key
            )
            
            with ResponseQueueContext(job_id) as queue:
                result = check_response_queue(queue, timeout=10)
                
                if result and result.get('status') == 'success':
                    return result.get('is_dir', False)
                return False
                
        except Exception as e:
            return False

    def is_remote_file(self, partial_remote_path):
        """Check if a remote path is a file.
        
        Args:
            partial_remote_path: The path to check
            
        Returns:
            True if path is a file, False otherwise
        """
        return not self.is_remote_directory(partial_remote_path)

    def prompt_and_rename(self):
        """Prompt user for new name and rename the selected file/directory.
        
        Returns:
            True if rename was successful, False otherwise
        """
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            self.message_signal.emit("No item selected")
            return False
            
        index = selection[0]
        filename = index.data(Qt.DisplayRole)
        
        new_name, ok = QInputDialog.getText(
            self, 'Rename', 'Enter new name:',
            text=filename
        )
        
        if ok and new_name and new_name != filename:
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory', '/')
            full_path = self.get_normalized_remote_path(current_dir, filename)
            return self.sftp_rename(full_path, new_name)
        
        return False

    def prompt_and_create_directory(self):
        """Prompt user for directory name and create it.
        
        Returns:
            True if directory was created, False otherwise
        """
        dir_name, ok = QInputDialog.getText(
            self, 'New Directory', 'Enter directory name:'
        )
        
        if ok and dir_name:
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_remote_directory', '/')
            full_path = self.get_normalized_remote_path(current_dir, dir_name)
            return self.sftp_mkdir(full_path)
        
        return False
