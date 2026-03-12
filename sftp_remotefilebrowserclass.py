from sftp_filebrowserclass import FileBrowser
from PyQt6.QtWidgets import QTableView, QFileDialog, QMessageBox, QInputDialog, QHeaderView, QMenu, QProgressDialog, QApplication
from PyQt6.QtCore import QModelIndex, QTimer, QThread
from icecream import ic
import os
import stat
import time

from sftp_remotefiletablemodel import RemoteFileTableModel
from sftp_qt_compat import Qt
from sftp_transfer_handler import TreePopulateWorker, DirectoryTransferTask, TraversalWorker
from sftp_creds import get_credentials
from sftp_sortfiltermodel import DirectoryFirstSortProxyModel
from sftp_creds import (get_credentials, create_random_integer, set_credentials,
                        verify_credential_update, verify_directory_consistency)
from sftp_downloadworkerclass import add_sftp_job
from sftp_preferences import get_preferences

# SECURITY: Debug logging to /tmp is DISABLED to prevent sensitive information leakage
# The /tmp directory is world-readable and could expose file paths and operations
# Use the icecream (ic) function for debugging instead, which goes to stderr


class RemoteFileBrowser(FileBrowser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        self.model = RemoteFileTableModel(self.session_id)
        
        # Connect model signals for status and loading feedback
        self.model.status_message.connect(self.message_signal.emit)
        self.model.loading_started.connect(lambda: self.progressBar.setRange(0, 0))
        self.model.loading_finished.connect(lambda: self.progressBar.setRange(0, 100))
        self.model.loading_finished.connect(lambda: self.progressBar.setValue(100))
        
        self.proxy_model = DirectoryFirstSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.table.setModel(self.proxy_model)

        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Set fixed row height for consistent appearance
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)

        # Make all columns resizable
        self.table.horizontalHeader().setSectionResizeMode(Qt.HeaderView_Interactive)

        # Set column widths to prevent text truncation
        self.table.setColumnWidth(0, 250)  # Name column - wide enough for most filenames
        self.table.setColumnWidth(1, 80)   # Size column
        self.table.setColumnWidth(2, 90)   # Permissions column
        self.table.setColumnWidth(3, 140)  # Modified column

        # Add these lines to enable full row selection
        self.table.setSelectionBehavior(Qt.TableView_SelectRows)
        self.table.setSelectionMode(Qt.TableView_ExtendedSelection)  # Allow Ctrl+Click and Shift+Click multi-select

        # Enable sorting and set initial sort column
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)

        # Don't initialize model here - defer until explicitly called
        # This allows credentials to be fully set before making SFTP calls
        self._initialized = False

    def initialize(self):
        """Initialize the model - called after connection is ready"""
        if self._initialized:
            ic(f"RemoteFileBrowser.initialize: already initialized, skipping")
            return
        self._initialized = True
        self.initialize_model()

    @property
    def session_api(self):
        """Get the session API from the parent class, initializing it if needed.
        RemoteFileBrowser shares the session with the parent FileBrowser class."""
        return super().session_api

    def get_files(self, force_refresh=True):
        """Get files from remote server, always refreshing by default."""
        self.model.get_files(force_refresh=force_refresh)

    def initialize_model(self):
        creds = get_credentials(self.session_id)
        stored_dir = creds.get('current_remote_directory', '.')
        ic(f"initialize_model: session_id={self.session_id}, stored_dir={stored_dir}")

        # Use the stored directory - it's the source of truth
        # get_remote_cwd_direct() creates a new SSH session which always returns the HOME directory
        # not the actual current directory we want to be in
        if stored_dir and stored_dir != '.' and stored_dir.startswith('/'):
            current_dir = stored_dir
            ic(f"Using stored directory: {current_dir}")
        else:
            # Only query server if we don't have a valid absolute directory
            ic(f"No valid stored directory, querying server...")
            current_dir = self.get_remote_cwd_direct()
            if current_dir:
                ic(f"Got cwd from server: {current_dir}")
                set_credentials(self.session_id, 'current_remote_directory', current_dir)
            else:
                current_dir = '/'
                ic(f"Failed to get cwd, using root: {current_dir}")
                set_credentials(self.session_id, 'current_remote_directory', current_dir)

        # Load files for current directory (single connection)
        # Use force_refresh=False to avoid redundant connection
        if not self.model.file_list:
            self.model.get_files(force_refresh=True, directory=current_dir)
        else:
            self.model.get_files(force_refresh=True, directory=current_dir)

        # Update UI without making another connection
        self.message_signal.emit(f"{current_dir}")

        # Defer column resizing to avoid blocking UI during initialization
        QTimer.singleShot(100, self.table.resizeColumnsToContents)

    def is_remote_browser(self):
        return True

    def prompt_and_create_directory(self):
        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            try:
                # Get current remote directory and construct full path
                creds = get_credentials(self.session_id)
                current_dir = creds.get('current_remote_directory', '.')
                full_path = self.get_normalized_remote_path(current_dir, directory_name)
                
                # Create the directory with full path
                self.sftp_mkdir(full_path)
                self.message_signal.emit(f"'{full_path}' created successfully.")
                # Force refresh to show new directory
                self.model.get_files(force_refresh=True)
                self.notify_observers()
            except (OSError, IOError, RuntimeError) as e:
                self.message_signal.emit(f"Error creating directory: {e}")

    def sftp_getcwd(self, timeout=30):
        if self.session_api is None:
            self.message_signal.emit("sftp_getcwd() - Session API not initialized")
            return None

        try:
            result = self.session_api.getcwd()
            ic(f"sftp_getcwd: returned {result}")
            return result
        except (OSError, IOError, RuntimeError) as e:
            ic(f"sftp_getcwd: {e}")
            return None

    def get_remote_cwd_direct(self):
        """
        Get the current working directory from the remote server.
        Uses the session API for proper connection management.
        """
        try:
            result = self.session_api.getcwd()
            ic(f"get_remote_cwd_direct: Got cwd from server: {result}")
            return result
        except (OSError, IOError, RuntimeError) as e:
            ic(f"get_remote_cwd_direct error: {e}")
            return None

    def close_sftp_connection(self):
        """Close the SFTP connection"""
        try:
            if hasattr(self, 'sftp') and self.sftp:
                try:
                    self.sftp.close()
                except (OSError, IOError, RuntimeError):
                    pass
                self.sftp = None
        except (OSError, IOError, RuntimeError):
            pass

    def change_directory(self, path, force_refresh=True):
        """Change to a directory - handles both relative and complete paths"""
        creds = get_credentials(self.session_id)
        
        try:
            if path == "..":
                head, tail = self.split_path(creds.get('current_remote_directory'))
                new_path = head
            elif self.is_complete_path(path):
                new_path = path
            else:
                current_dir = creds.get('current_remote_directory', '.')
                new_path = self.get_normalized_remote_path(current_dir, path)

            if not force_refresh and new_path in self.model.cache and time.time() - self.model.cache_time.get(new_path, 0) < self.model.cache_duration:
                set_credentials(self.session_id, 'current_remote_directory', new_path)
                self.model.file_list = self.model.cache[new_path]
                self.model.layoutChanged.emit()  # Notify view of data change
                self.proxy_model.invalidate()  # Force proxy to re-sort
                self.message_signal.emit(f"{new_path}")
                self.notify_observers()
                self.table.viewport().update()
                return True
            
            self.progressBar.setRange(0, 0)
            
            try:
                ops = self.get_sftp_operations()
                ops.chdir(new_path.replace("\\", "/"))
            except Exception as e:
                self.progressBar.setRange(0, 100)
                self.message_signal.emit(f"change_directory() failed: {e}")
                return False
            
            self.progressBar.setRange(0, 100)

            set_credentials(self.session_id, 'current_remote_directory', new_path)
            
            if not verify_credential_update(self.session_id, 'current_remote_directory', new_path, "change_directory"):
                ic(f"CRITICAL: Failed to update credentials to {new_path}")
            
            is_valid, current_dir = verify_directory_consistency(self.session_id, "change_directory")
            if not is_valid:
                ic(f"WARNING: Directory '{current_dir}' may be invalid")
            
            self.message_signal.emit(f"{new_path}")
            self.model.invalidate_cache(new_path)
            self.model.get_files(force_refresh=True, directory=new_path)
            
            # Invalidate proxy to force re-sort with new data
            self.proxy_model.invalidate()
            
            self.notify_observers()
            self.table.viewport().update()
            return True

        except (OSError, IOError, RuntimeError) as e:
            ic(f"change_directory EXCEPTION: {e}")
            self.message_signal.emit(f"change_directory() {e}")
            return False

    def double_click_handler(self, index):
        creds = get_credentials(self.session_id)
        try:
            if not index.isValid():
                return False

            # IMPORTANT: Map the visual index to source model index since proxy model sorts rows
            source_index = self.proxy_model.mapToSource(index)
            
            # Get the data from the source model
            filename_index = self.model.index(source_index.row(), 0)
            filename = self.model.data(filename_index, Qt.DisplayRole)

            # Remove type prefix if present ([DIR], [FILE], 📁, 📄, etc.)
            prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
            for prefix in prefixes:
                if filename.startswith(prefix):
                    filename = filename[len(prefix):].lstrip()
                    break
            
            # Early return for parent directory navigation
            if filename == "..":
                return self.change_directory("..")

            # Determine the full path
            current_dir = creds.get('current_remote_directory', '.')
            
            # If current_dir is relative, resolve it
            if current_dir == '.':
                home_dir = self.sftp_getcwd()
                if home_dir:
                    current_dir = home_dir
                    set_credentials(self.session_id, 'current_remote_directory', current_dir)
            
            if self.is_complete_path(filename):
                path = filename
            else:
                path = self.get_normalized_remote_path(current_dir, filename)

            # Check if the path is a directory or a file
            if self.is_remote_directory(path):
                return self.change_directory(path)
            elif self.is_remote_file(path):
                local_path, _ = QFileDialog.getSaveFileName(self, "Save File", filename)
                if local_path:
                    self.upload_download(path, local_path)
                    self.message_signal.emit(f"Downloaded file: {path} to {local_path}")
                    return True
                else:
                    return False
            else:
                self.message_signal.emit(f"Unable to process: {path}. It's neither a directory nor a file.")
                return False

        except (OSError, IOError, RuntimeError) as e:
            ic(e)
            self.message_signal.emit(f"Error processing: {filename}. Details: {str(e)}")
            return False

    def get_selected_item(self):
        selected_indexes = self.table.selectedIndexes()
        if selected_indexes:
            # With SelectRows mode, get the first column of the selected row
            first_index = selected_indexes[0]
            filename_index = self.model.index(first_index.row(), 0)
            return self.model.data(filename_index, Qt.DisplayRole)
        return None

    def change_directory_handler(self):
        selected_item, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        if self.is_remote_directory(selected_item):
            self.change_directory(selected_item)

    def remove_trailing_dot(self, s):
        if s.endswith('/.'):
            return s[:-1]  # Remove the last character (dot)
        else:
            return s

    def remove_directory_with_prompt(self, remote_path=None, always=0):
        self.always = always
        creds = get_credentials(self.session_id)
        
        # Get selected items
        current_browser = self.table
        if current_browser is None or not isinstance(current_browser, QTableView):
            return
            
        indexes = current_browser.selectedIndexes()
        if not indexes:
            return
            
        # Get unique rows from selected indexes
        processed_rows = set()
        selected_paths = []
        
        for index in indexes:
            row = index.row()
            if row in processed_rows:
                continue
            processed_rows.add(row)
            
            # Get filename from first column
            filename_index = index.sibling(row, 0)
            selected_item = current_browser.model().data(filename_index, Qt.DisplayRole)
            
            # Remove type prefix if present
            filename = selected_item
            prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
            for prefix in prefixes:
                if filename.startswith(prefix):
                    filename = filename[len(prefix):].lstrip()
                    break
            
            # Get current remote directory
            if creds.get('current_remote_directory') == '.':
                temp_path = self.sftp_getcwd()
                if temp_path:
                    set_credentials(self.session_id, 'current_remote_directory', self.remove_trailing_dot(temp_path))
            
            full_path = os.path.join(creds.get('current_remote_directory'), filename)
            selected_paths.append(full_path)
        
        if not selected_paths:
            return
        
        # Prompt for confirmation for all selected items
        if not self.always:
            if len(selected_paths) == 1:
                prompt_msg = f"Are you sure you want to delete '{selected_paths[0]}'?"
            else:
                prompt_msg = f"Are you sure you want to delete {len(selected_paths)} items?"
                
            response = QMessageBox.question(
                None,
                'Confirm Delete',
                prompt_msg,
                Qt.MsgBtn_Yes | Qt.MsgBtn_No,
                Qt.MsgBtn_No
            )
            if response != Qt.MsgBtn_Yes:
                return
        
        # Remove each selected item
        for remote_path in selected_paths:
            try:
                # Check if the remote path exists
                if not self.sftp_exists(remote_path):
                    self.message_signal.emit(f"Remote path '{remote_path}' does not exist.")
                    continue
                
                # Check if it's a file
                if self.is_remote_file(remote_path):
                    self.sftp_remove(remote_path)
                    self.message_signal.emit(f"File '{remote_path}' removed successfully.")
                    continue
                
                # It's a directory - recursively remove
                self._remove_remote_directory_recursive(remote_path)
                self.message_signal.emit(f"Directory '{remote_path}' removed successfully.")
            except (OSError, IOError, RuntimeError) as e:
                self.message_signal.emit(f"remove_directory_with_prompt() error: {e}")
        
        # Refresh the browser
        self.model.get_files(force_refresh=True)
    
    def _remove_remote_directory_recursive(self, remote_path):
        """Recursively remove a remote directory and its contents"""
        # Check if directory exists
        if not self.sftp_exists(remote_path):
            return
            
        # Get directory contents
        directory_contents_attr = self.sftp_listdir_attr(remote_path)
        if directory_contents_attr is False:
            # Empty directory, just remove it
            self.sftp_rmdir(remote_path)
            return
        
        # Separate files and subdirectories
        subdirectories = [entry for entry in directory_contents_attr if stat.S_ISDIR(entry.st_mode)]
        files = [entry for entry in directory_contents_attr if stat.S_ISREG(entry.st_mode)]
        
        # Remove files
        for entry in files:
            entry_path = os.path.join(remote_path, entry.filename)
            self.sftp_remove(entry_path)
        
        # Recursively remove subdirectories
        for entry in subdirectories:
            entry_path = os.path.join(remote_path, entry.filename)
            self._remove_remote_directory_recursive(entry_path)
        
        # Remove the directory itself
        self.sftp_rmdir(remote_path)
        creds = get_credentials(self.session_id)
        if remote_path is None or remote_path is False:
            # current_browser = self.focusWidget()
            current_browser = self.table
            if current_browser is not None and isinstance(current_browser, QTableView):
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    # ALWAYS use column 0 for filename
                    filename_index = current_index.sibling(current_index.row(), 0)
                    selected_item = current_browser.model().data(filename_index, Qt.DisplayRole)
                    
                    # Remove type prefix if present
                    prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
                    for prefix in prefixes:
                        if selected_item.startswith(prefix):
                            selected_item = selected_item[len(prefix):].lstrip()
                            break

                    if creds.get('current_remote_directory') == '.':
                        temp_path = self.sftp_getcwd()
                    else:
                        temp_path = creds.get('current_remote_directory')
                    set_credentials(self.session_id, 'current_remote_directory', self.remove_trailing_dot(temp_path))
                    remote_path = os.path.join(creds.get('current_remote_directory'), selected_item)
            else:
                return
        try:
            # Check if the remote path exists
            if not self.sftp_exists(remote_path):
                self.message_signal.emit(f"Remote path '{remote_path}' does not exist.")
                return
            # Check if it's a file
            if self.is_remote_file(remote_path):
                self.sftp_remove(remote_path)
                self.message_signal.emit(f"File '{remote_path}' removed successfully.")
                return
            # Get attributes of directory contents
            directory_contents_attr = self.sftp_listdir_attr(remote_path)
            if directory_contents_attr is False:
                self.message_signal.emit(f"Failed to get contents of '{remote_path}'. It might be an empty directory.")
                # Try to remove the directory even if it's empty
                self.sftp_rmdir(remote_path)
                self.message_signal.emit(f"Empty directory '{remote_path}' removed successfully.")
                return
            # Separate files and subdirectories
            subdirectories = [entry for entry in directory_contents_attr if stat.S_ISDIR(entry.st_mode)]
            files = [entry for entry in directory_contents_attr if stat.S_ISREG(entry.st_mode)]
            if (subdirectories or files) and not self.always:
                response = QMessageBox.question(
                    None,
                    'Confirmation',
                    f"The directory '{remote_path}' contains subdirectories or files. Do you want to remove them all?",
                    Qt.MsgBtn_Yes | Qt.MsgBtn_No | Qt.MsgBtn_YesToAll,
                    Qt.MsgBtn_No
                )
                if response == Qt.MsgBtn_YesToAll:
                    self.always = 1
                if response == Qt.MsgBtn_No:
                    return

            # Remove files
            for entry in files:
                entry_path = os.path.join(remote_path, entry.filename)
                self.message_signal.emit(f"Removing file: {entry_path}")
                self.sftp_remove(entry_path)
            # Recursively remove subdirectories
            for entry in subdirectories:
                entry_path = os.path.join(remote_path, entry.filename)
                self.message_signal.emit(f"Recursing into subdirectory: {entry_path}")
                self.remove_directory_with_prompt(entry_path, self.always)
            # Remove the directory
            self.sftp_rmdir(remote_path)
            self.message_signal.emit(f"Directory '{remote_path}' removed successfully.")
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"remove_directory_with_prompt() error: {e}")
        finally:
            # Note: invalidate_cache is redundant since get_files with force_refresh=True bypasses cache
            self.model.get_files(force_refresh=True)

    def upload_download(self, optionalpath=None, local_destination=None):
        """Upload or download files. When optionalpath and local_destination are provided,
        downloads the specific remote file to the specific local destination."""
        job_id = create_random_integer()
        creds = get_credentials(self.session_id)

        # Handle current remote directory initialization - get REAL CWD from server
        if creds.get('current_remote_directory') == '.':
            current_remote_directory = self.sftp_getcwd()
            if current_remote_directory:
                set_credentials(self.session_id, 'current_remote_directory', current_remote_directory)
            else:
                current_remote_directory = '/'
        else:
            current_remote_directory = creds.get('current_remote_directory')

        current_browser = self.table
        
        if current_browser is None:
            ic("ERROR: current_browser is None!")
            self.message_signal.emit("Error: No table browser found")
            return
            
        if not isinstance(current_browser, QTableView):
            self.message_signal.emit("Error: Browser is not a table view")
            return
            
        indexes = current_browser.selectedIndexes()
        
        if not indexes:
            self.message_signal.emit("No files selected for transfer")
            return
            
        processed_rows = set()  # Track processed rows to avoid duplicates
        has_valid_item = False
        action = None

        # Move these outside the loop so they persist across iterations
        skip_all = False
        overwrite_all = False
        resume_all = False

        for index in indexes:
            row = index.row()
            if row in processed_rows:
                continue
            processed_rows.add(row)

            # Always get the data from the first column (filename)
            # Use sibling(row, 0) to correctly handle proxy model mapping
            filename_index = index.sibling(row, 0)
            selected_item_text = current_browser.model().data(filename_index, Qt.DisplayRole)
            attr_item = current_browser.model().data(filename_index, Qt.UserRole)
            
            # Check if it's a directory using cached metadata
            is_dir = False
            if attr_item:
                is_dir = stat.S_ISDIR(attr_item.st_mode)
            elif selected_item_text == "..":
                is_dir = True
            
            # Remove type prefix if present ([DIR], [FILE], 📁, 📄, etc.)
            filename = selected_item_text
            prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
            for prefix in prefixes:
                if filename.startswith(prefix):
                    filename = filename[len(prefix):].lstrip()
                    break

            if optionalpath:
                filename = optionalpath
                # If optionalpath is provided, we might still need to know if it's a dir
                # but usually it's for specific files. For now, assume False if not in model.
                if not attr_item: is_dir = self.is_remote_directory(filename)

            if filename:
                try:
                    # Determine if we should use optionalpath or filename
                    use_optional_path = optionalpath and isinstance(optionalpath, str)

                    if use_optional_path:
                        # optionalpath is provided, use it directly
                        remote_entry_path = optionalpath
                    else:
                        # Normal case - use filename, join with current directory
                        is_complete = self.is_complete_path(filename)
                        if is_complete:
                            remote_entry_path = filename
                        else:
                            # Join with current directory
                            if current_remote_directory == '/':
                                remote_entry_path = '/' + filename
                            else:
                                remote_entry_path = current_remote_directory + '/' + filename

                    # Normalize to remove any double slashes or trailing slashes
                    remote_entry_path = remote_entry_path.replace('//', '/').rstrip('/')

                    # Use provided local_destination or construct from current local directory
                    if local_destination:
                        local_entry_path = local_destination
                    else:
                        local_base_path = creds.get('current_local_directory')
                        local_entry_path = os.path.join(local_base_path, filename)

                    if is_dir:
                        # For directories, destination should be local_base_path + directory name
                        # This preserves the directory structure: e.g., /mnt/f/__Drivers -> /Downloads/__Drivers
                        dest_dir = os.path.join(local_base_path, filename)
                        if not skip_all and not overwrite_all and not resume_all and os.path.exists(local_entry_path):
                            prefs = get_preferences()
                            if prefs.get_bool("overwrite_on_transfer", False):
                                overwrite_all = True
                            else:
                                action = self.prompt_overwrite(local_entry_path)
                                if action == "cancel":
                                    return
                                elif action == "skip":
                                    continue
                                elif action == "skip_all":
                                    skip_all = True
                                    continue
                                elif action == "overwrite_all":
                                    overwrite_all = True
                                elif action == "resume_all":
                                    resume_all = True

                        if not skip_all:
                            self.download_directory(remote_entry_path, dest_dir, skip_all, overwrite_all, resume_all)
                    else:
                        # Handle individual file
                        if not skip_all and not overwrite_all and not resume_all and os.path.exists(local_entry_path):
                            prefs = get_preferences()
                            if prefs.get_bool("overwrite_on_transfer", False):
                                overwrite_all = True
                            else:
                                action = self.prompt_overwrite(local_entry_path)
                                if action == "cancel":
                                    return
                                elif action == "skip":
                                    continue
                                elif action == "skip_all":
                                    skip_all = True
                                    continue
                                elif action == "overwrite_all":
                                    overwrite_all = True
                                elif action == "resume_all":
                                    resume_all = True
                                # Note: "overwrite" (single) and "resume" (single) don't set flags,
                                # so user will be prompted again for next file - this is intentional

                        if not skip_all:
                            # Check action set by prompt - overwrite_all or resume_all set flags,
                            # but single "overwrite" or "resume" is stored in action
                            action_result = locals().get('action', '')
                            resume = (not overwrite_all and action_result == "resume")
                            overwrite = (not overwrite_all and action_result == "overwrite")
                            
                            try:
                                creds = get_credentials(self.session_id)
                                if resume:
                                    command = "resume"
                                elif overwrite:
                                    command = "download"  # Overwrite means re-download
                                else:
                                    command = "download"
                                add_sftp_job(
                                    remote_entry_path, True,  # source is remote
                                    local_entry_path, False,  # dest is local
                                    creds.get('hostname', ''),
                                    creds.get('username', ''),
                                    creds.get('password', ''),
                                    creds.get('port', 22),
                                    command,
                                    job_id,
                                    creds.get('key')
                                )
                                self.transfer_started.emit(str(job_id))
                            except Exception as e:
                                self.message_signal.emit(f"Download failed: {e}")
                            
                            self.message_signal.emit(f"Starting transfer: {remote_entry_path}")

                    has_valid_item = True

                except (OSError, IOError, RuntimeError) as e:
                    error_message = f"upload_download() encountered an error: {str(e)}"
                    self.message_signal.emit(error_message)
            else:
                self.message_signal.emit("No valid path provided.")

        if not has_valid_item:
            self.message_signal.emit("No valid items selected.")

        # Force refresh after operations
        # Note: invalidate_cache is redundant since get_files with force_refresh=True bypasses cache
        self.model.get_files(force_refresh=True)

    def download_directory(self,
                        source_directory: str,
                        destination_directory: str,
                        skip_all: bool = False,
                        overwrite_all: bool = False, 
                        resume_all: bool = False) -> None:
        """
        Download a directory and its contents from the remote server.
        Uses DirectoryTransferTask for thread-safe background execution.
        """
        ic(f"download_directory called: source={source_directory}, dest={destination_directory}")
        
        # Cancel any existing transfer before starting a new one
        if hasattr(self, '_current_traversal_thread') and self._current_traversal_thread:
            if self._current_traversal_thread.isRunning():
                self.cancel_current_transfer()
        
        thread = QThread()
        worker = DirectoryTransferTask(
            self.session_id, source_directory, destination_directory,
            is_source_remote=True, is_dest_remote=False,
            skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all,
            browser=self,
            auto_overwrite=True  # Auto-overwrite to avoid blocking on prompts
        )
        worker.moveToThread(thread)
        
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        # Connect signals
        worker.job_added.connect(lambda jid: self.transfer_started.emit(jid) if hasattr(self, 'transfer_started') and self.transfer_started else None)
        worker.error.connect(lambda err: self.message_signal.emit(f"Download error: {err}"))
        
        self._current_traversal_worker = worker
        self._current_traversal_thread = thread
        
        thread.start()
        self.message_signal.emit(f"Started download of {source_directory}")

    def cancel_current_transfer(self):
        """Cancel the current directory transfer"""
        if hasattr(self, '_current_traversal_worker') and self._current_traversal_worker:
            self._current_traversal_worker.cancel()
            self.message_signal.emit("Cancelling transfer...")
            self._current_traversal_worker = None
        if hasattr(self, '_current_traversal_thread') and self._current_traversal_thread:
            self._current_traversal_thread.quit()
            self._current_traversal_thread.wait()
            self._current_traversal_thread = None
    
    def cleanup(self):
        """Cleanup browser resources including running threads"""
        if hasattr(self, '_current_traversal_worker') and self._current_traversal_worker:
            self._current_traversal_worker.cancel()
        if hasattr(self, '_current_traversal_thread') and self._current_traversal_thread:
            self._current_traversal_thread.quit()
            self._current_traversal_thread.wait()
        super().cleanup()

    def get_current_directory(self):
        """Get the current remote directory"""
        creds = get_credentials(self.session_id)
        return creds.get('current_remote_directory', '.')

    def navigate_to_bookmark(self, path):
        """Navigate to a bookmarked remote directory"""
        try:
            # Change to the bookmarked directory
            success = self.change_directory(path, force_refresh=True)
            if success:
                self.message_signal.emit(f"Navigated to: {path}")
                return True
            else:
                self.message_signal.emit(f"Failed to navigate to: {path}")
                return False
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error navigating to bookmark: {e}")

    def populate_tree_view(self):
        """Build tree starting from current remote directory as root"""
        from PyQt6.QtWidgets import QTreeWidgetItem
        
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_remote_directory', '/')
        
        ic(f"populate_tree_view called for session {self.session_id}, current_dir={current_dir}")
        ic(f"session_api available: {self.session_api is not None}")
        
        # Store root and current paths
        self._tree_root_path = current_dir
        self._tree_current_path = current_dir
        
        # Update UI
        self.tree_path_input.setText(current_dir)
        self._update_tree_up_button()
        
        # Build tree from root
        self._build_tree_from_root(current_dir, current_dir)
    
    def _build_tree_from_root(self, root_path, current_path):
        """Build tree starting from root_path, highlighting current_path"""
        from PyQt6.QtWidgets import QTreeWidgetItem
        
        self.tree_widget.clear()
        
        try:
            # Create root item
            root_item = QTreeWidgetItem(self.tree_widget)
            root_name = os.path.basename(root_path) or root_path
            root_item.setText(0, "📁 " + root_name)
            root_item.setData(0, Qt.UserRole, {'path': root_path, 'is_dir': True, 'is_root': True})
            root_item.setExpanded(True)
            
            # If current is same as root, highlight it
            if root_path == current_path:
                self._mark_current_item(root_item)
            
            # Populate subdirectories lazily
            self._populate_tree_children(root_item, root_path)
            
            # Expand path to current directory if it's a subdirectory
            if current_path.startswith(root_path) and current_path != root_path:
                self._expand_to_path(root_item, root_path, current_path)
            
        except (OSError, IOError, RuntimeError) as e:
            ic(f"Error building tree: {e}")
            self.tree_status_label.setText(f"Error: {e}")
    
    def _populate_tree_children(self, parent_item, path):
        """Populate tree with subdirectories of the given remote path (lazy loading) using paramiko"""
        from PyQt6.QtWidgets import QTreeWidgetItem
        from PyQt6.QtCore import QThreadPool
        
        def on_finished(pop_path, directories):
            self.tree_status_label.setText(f"✅ {pop_path} - {len(directories)} subdirectories")
            for attr in directories:
                child_item = QTreeWidgetItem(parent_item)
                child_item.setText(0, "📁 " + attr.filename)
                full_path = os.path.join(pop_path, attr.filename) if pop_path != '/' else '/' + attr.filename
                child_item.setData(0, Qt.UserRole, {'path': full_path, 'is_dir': True, 'is_root': False})
                dummy_child = QTreeWidgetItem(child_item)
                dummy_child.setText(0, "⏳ Loading...")
            self.tree_widget.update()
        
        def on_error(pop_path, error_msg):
            self.tree_status_label.setText(f"❌ Error: {error_msg[:50]}")
        
        worker = TreePopulateWorker(self.session_id, path, is_remote=True)
        worker.signals.finished.connect(on_finished)
        worker.signals.error.connect(on_error)
        
        self.tree_status_label.setText(f"⏳ Loading {path}...")
        QThreadPool.globalInstance().start(worker)

    def tree_double_click_handler(self, item, column):
        """Handle double-click on tree item - navigate to that directory"""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        path = data.get('path')
        is_dir = data.get('is_dir', False)
        
        if not is_dir:
            return
        
        # Navigate to the directory
        self.change_directory(path)
        
        # Update credentials so list view shows the same directory
        set_credentials(self.session_id, 'current_remote_directory', path)
        
        # Refresh the tree to show new location as root
        self.populate_tree_view()

    def tree_go_up(self):
        """Navigate to parent directory and make it the new root"""
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_remote_directory', '/')
        
        # Get parent path
        if current_dir == '/' or not current_dir:
            self.message_signal.emit("Already at root directory")
            return
        
        parent_dir = os.path.dirname(current_dir)
        if not parent_dir:
            parent_dir = '/'
        
        # Navigate up
        self.change_directory(parent_dir)
        
        # Rebuild tree with new root
        self.populate_tree_view()

    def tree_path_navigate(self):
        """Navigate to path entered in tree path input"""
        path = self.tree_path_input.text().strip()

        if not path:
            return

        # Normalize path (remove trailing slash except for root)
        path = path.rstrip('/')
        if not path:
            path = '/'

        # Check if path exists by trying to list it
        try:
            result = self.sftp_listdir_attr(path)
            if result is None or result is False:
                self.tree_status_label.setText(f"❌ Cannot access: {path}")
                return
        except (OSError, IOError, RuntimeError) as e:
            self.tree_status_label.setText(f"❌ Error: {str(e)[:50]}")
            return

        # Navigate to the path
        self.change_directory(path)

        # Rebuild tree with new root
        self.populate_tree_view()

    def tree_download_selected(self):
        """Download selected remote directory to local"""
        
        # Get selected item
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            self.tree_status_label.setText("❌ No directory selected")
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        path = data.get('path')
        is_dir = data.get('is_dir', False)

        if not is_dir:
            self.tree_status_label.setText("❌ Selected item is not a directory")
            return

        # Get local directory
        creds = get_credentials(self.session_id)
        local_dir = creds.get('current_local_directory', os.path.expanduser('~'))

        # Download the directory
        self.message_signal.emit(f"⬇️ Queuing download: {path} -> {local_dir}")
        self.download_directory(path, local_dir)

    def tree_download_all(self):
        """Download all visible remote directories to local"""
        
        # Get root item
        root = self.tree_widget.invisibleRootItem()
        if root.childCount() == 0:
            self.tree_status_label.setText("❌ No directories to download")
            return

        # Get local directory
        creds = get_credentials(self.session_id)
        local_dir = creds.get('current_local_directory', os.path.expanduser('~'))

        # Count directories to download
        download_count = 0
        for i in range(root.child(0).childCount()):
            item = root.child(0).child(i)
            data = item.data(0, Qt.UserRole)
            if data and data.get('is_dir', False):
                path = data.get('path')
                self.message_signal.emit(f"⬇️ Queuing download: {path} -> {local_dir}")
                self.download_directory(path, local_dir)
                download_count += 1

        if download_count > 0:
            self.tree_status_label.setText(f"✅ Queued {download_count} directories for download")
        else:
            self.tree_status_label.setText("❌ No directories to download")

    def tree_delete_selected(self):
        """Delete selected remote directory"""
        from PyQt6.QtWidgets import QMessageBox

        # Get selected item
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            self.tree_status_label.setText("❌ No directory selected")
            return

        item = selected_items[0]
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        path = data.get('path')
        is_dir = data.get('is_dir', False)
        is_root = data.get('is_root', False)

        if is_root:
            self.tree_status_label.setText("❌ Cannot delete root directory")
            return

        if not is_dir:
            self.tree_status_label.setText("❌ Selected item is not a directory")
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self, 'Confirm Delete',
            f"Are you sure you want to delete the remote directory:\n\n{path}\n\nThis action cannot be undone!",
            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
            Qt.MsgBtn_No
        )

        if reply != Qt.MsgBtn_Yes:
            return

        try:
            # Remove the remote directory using existing method
            self.remove_directory_with_prompt(path, always=1)  # always=1 to skip confirmation dialog
            self.message_signal.emit(f"🗑️ Deleted remote: {path}")
            self.tree_status_label.setText(f"✅ Deleted: {os.path.basename(path)}")

            # Refresh tree view
            self.populate_tree_view()

            # Refresh file table
            self.model.get_files()
            self.notify_observers()
        except (OSError, IOError, RuntimeError) as e:
            self.tree_status_label.setText(f"❌ Error deleting: {str(e)[:50]}")
            QMessageBox.critical(self, "Error", f"Failed to delete remote directory:\n{str(e)}")

    def _update_tree_up_button(self):
        """Update up button state based on current directory"""
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_remote_directory', '/')
        
        # Disable if at filesystem root
        self.tree_up_btn.setEnabled(current_dir != '/' and current_dir != '')
    
    def tree_context_menu_handler(self, pos):
        """Handle context menu on tree widget"""
        from PyQt6.QtWidgets import QMenu
        
        item = self.tree_widget.itemAt(pos)
        if not item:
            return
        
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        path = data.get('path')
        is_root = data.get('is_root', False)
        
        menu = QMenu()
        
        if not is_root:
            open_action = menu.addAction("📂 Open")
        refresh_action = menu.addAction("🔄 Refresh")
        if not is_root:
            menu.addSeparator()
            download_action = menu.addAction("⬇️ Download Directory")
        
        action = menu.exec(self.tree_widget.mapToGlobal(pos))
        
        if action == open_action:
            self.change_directory(path)
            self._tree_current_path = path
            self._mark_current_item(item)
            self.tree_path_input.setText(path)
        elif action == refresh_action:
            self.populate_tree_view()
        elif action == download_action:
            creds = get_credentials(self.session_id)
            local_dir = creds.get('current_local_directory', os.path.expanduser('~'))
            self.download_directory(path, local_dir)
