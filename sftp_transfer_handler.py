from PyQt6.QtWidgets import QInputDialog, QMessageBox
from sftp_qt_compat import Qt
from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import add_sftp_job
from sftp_preferences import get_preferences
import os
from icecream import ic


class TransferHandlerMixin:
    """Mixin class providing file transfer functionality.
    
    This class handles:
    - Upload/download operations
    - Directory traversal and batch transfers
    - Overwrite prompts and conflict resolution
    """

    transfer_started = None

    def upload_download(self, local_destination=None, optionalpath=None):
        """Handle upload or download based on selection.
        
        Args:
            local_destination: Optional local destination path
            optionalpath: Optional remote path to use
        """
        if not self.table:
            self.message_signal.emit("Current browser is not a valid QTableView.")
            return

        selection = self.table.selectionModel().selectedRows()
        
        if selection:
            creds = get_credentials(self.session_id)
            current_remote_directory = creds.get('current_remote_directory', '/')
            
            has_valid_item = False
            skip_all = False
            overwrite_all = False
            resume_all = False
            
            prefixes = ['/mnt/', '/media/', '/Volumes/']
            
            for index in selection:
                filename = index.data()
                
                for prefix in prefixes:
                    if filename.startswith(prefix):
                        filename = filename[len(prefix):].lstrip()
                        break

                if optionalpath:
                    filename = optionalpath

                if filename:
                    try:
                        use_optional_path = optionalpath and isinstance(optionalpath, str)

                        if use_optional_path:
                            remote_entry_path = optionalpath
                        else:
                            is_complete = self.is_complete_path(filename)
                            if is_complete:
                                remote_entry_path = filename
                            else:
                                if current_remote_directory == '/':
                                    remote_entry_path = '/' + filename
                                else:
                                    remote_entry_path = current_remote_directory + '/' + filename

                        remote_entry_path = remote_entry_path.replace('//', '/').rstrip('/')

                        if local_destination:
                            local_entry_path = local_destination
                        else:
                            local_base_path = creds.get('current_local_directory')
                            local_entry_path = os.path.join(local_base_path, filename)

                        ic(f"upload_download: local_entry_path={repr(local_entry_path)}")

                        if self.is_remote_directory(remote_entry_path):
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
                                self.download_directory(remote_entry_path, local_entry_path, skip_all, overwrite_all, resume_all)
                        else:
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
                                command = "download"
                                if (not overwrite_all and locals().get('action') == "resume") or resume_all:
                                    command = "resume"
                                
                                ic(f"upload_download: DEBUG - remote_entry_path={repr(remote_entry_path)}")
                                ic(f"upload_download: DEBUG - local_entry_path={repr(local_entry_path)}")
                                ic(f"upload_download: DEBUG - command={command}")
                                
                                job_id = create_random_integer()
                                add_sftp_job(remote_entry_path, True, local_entry_path, False,
                                        self.init_hostname, self.init_username,
                                        self.init_password, self.init_port,
                                        command, job_id, self.init_key)
                                
                                if self.transfer_started:
                                    self.transfer_started.emit(str(job_id))
                                
                                self.message_signal.emit(f"Starting transfer: {remote_entry_path}")

                        has_valid_item = True

                    except (OSError, IOError, RuntimeError) as e:
                        error_message = f"upload_download() encountered an error: {str(e)}"
                        self.message_signal.emit(error_message)

            if not has_valid_item:
                self.message_signal.emit("No valid items selected.")
        else:
            self.message_signal.emit("No items selected.")

        self.model.get_files(force_refresh=True)

    def _get_transfer_action(self, target_path, skip_all, overwrite_all, resume_all, is_directory=False):
        """Determine the transfer action based on user choice and flags.
        
        Args:
            target_path: The target file/directory path
            skip_all: If True, skip all conflicts
            overwrite_all: If True, overwrite all conflicts
            resume_all: If True, resume all transfers
            is_directory: Whether the target is a directory
            
        Returns:
            Tuple of (action, skip_all, overwrite_all, resume_all)
        """
        if skip_all:
            return ("skip", skip_all, overwrite_all, resume_all)
        if overwrite_all:
            return ("overwrite" if not is_directory else "overwrite_dir", skip_all, overwrite_all, resume_all)
        if resume_all:
            return ("resume", skip_all, overwrite_all, resume_all)
            
        action = self.prompt_overwrite(target_path)
        
        if action == "skip":
            return ("skip", skip_all, overwrite_all, resume_all)
        elif action == "skip_all":
            return ("skip", True, overwrite_all, resume_all)
        elif action == "overwrite":
            return ("overwrite", skip_all, overwrite_all, resume_all)
        elif action == "overwrite_all":
            return ("overwrite", skip_all, True, resume_all)
        elif action == "resume":
            return ("resume", skip_all, overwrite_all, resume_all)
        elif action == "resume_all":
            return ("resume", skip_all, overwrite_all, True)
        else:
            return (None, skip_all, overwrite_all, resume_all)

    def _ensure_directory_exists(self, directory_path, is_remote=False):
        """Ensure a directory exists, creating it if necessary.
        
        Args:
            directory_path: The directory path to check/create
            is_remote: Whether the path is remote (True) or local (False)
        """
        if is_remote:
            parts = directory_path.strip('/').split('/')
            path = ''
            for part in parts:
                path += '/' + part
                if not self.sftp_exists(path):
                    self.sftp_mkdir(path)
        else:
            os.makedirs(directory_path, exist_ok=True)

    def traverse_and_transfer(self, source_dir, dest_dir, is_source_remote, is_dest_remote,
                              skip_all=False, overwrite_all=False, resume_all=False):
        """Traverse a directory and transfer all files.
        
        Args:
            source_dir: Source directory path
            dest_dir: Destination directory path
            is_source_remote: Whether source is remote
            is_dest_remote: Whether destination is remote
            skip_all: Skip all conflicts
            overwrite_all: Overwrite all conflicts
            resume_all: Resume all transfers
        """
        if is_source_remote:
            files = self.sftp_listdir_attr(source_dir)
        else:
            files = os.listdir(source_dir)
            
        for entry in files:
            if is_source_remote:
                filename = entry.get('filename', '')
                if entry.get('is_dir'):
                    continue
            else:
                filename = entry
                if os.path.isdir(os.path.join(source_dir, filename)):
                    continue
                    
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(dest_dir, filename)
            
            if os.path.exists(dest_path) and not skip_all and not overwrite_all and not resume_all:
                action = self.prompt_overwrite(dest_path)
                if action == "cancel":
                    continue
                elif action == "skip":
                    continue
                elif action == "skip_all":
                    skip_all = True
                    continue
                elif action == "overwrite_all":
                    overwrite_all = True
                elif action == "resume_all":
                    resume_all = True
                    
            command = "upload" if is_dest_remote else "download"
            if resume_all:
                command = "resume"
                
            job_id = create_random_integer()
            
            if is_source_remote and is_dest_remote:
                add_sftp_job(source_path, True, dest_path, True,
                            self.init_hostname, self.init_username,
                            self.init_password, self.init_port,
                            command, job_id, self.init_key)
            elif is_source_remote:
                add_sftp_job(source_path, True, dest_path, False,
                            self.init_hostname, self.init_username,
                            self.init_password, self.init_port,
                            command, job_id, self.init_key)
            else:
                add_sftp_job(source_path, False, dest_path, True,
                            self.init_hostname, self.init_username,
                            self.init_password, self.init_port,
                            command, job_id, self.init_key)
                            
            if self.transfer_started:
                self.transfer_started.emit(str(job_id))

    def upload_directory(self, source_directory, destination_directory, 
                         skip_all=False, overwrite_all=False, resume_all=False):
        """Upload a directory to remote server.
        
        Args:
            source_directory: Local source directory
            destination_directory: Remote destination directory
            skip_all: Skip all conflicts
            overwrite_all: Overwrite all conflicts
            resume_all: Resume all transfers
        """
        self._ensure_directory_exists(destination_directory, is_remote=True)
        self.traverse_and_transfer(
            source_directory, destination_directory,
            is_source_remote=False, is_dest_remote=True,
            skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all
        )
        self.message_signal.emit(f"Directory upload started: {source_directory}")

    def prompt_overwrite(self, item_path):
        """Prompt user for overwrite action.
        
        Args:
            item_path: The path of the item to overwrite
            
        Returns:
            String action: 'overwrite', 'skip', 'cancel', 'resume', 'overwrite_all', 'skip_all', 'resume_all'
        """
        msg = QMessageBox(self)
        msg.setIcon(Qt.MsgIcon_Question)
        msg.setText(f"File already exists:\n{item_path}")
        msg.setWindowTitle("File Exists")
        
        overwrite_btn = msg.addButton("Overwrite", Qt.MsgRole_ActionRole)
        skip_btn = msg.addButton("Skip", Qt.MsgRole_ActionRole)
        cancel_btn = msg.addButton(Qt.MsgBtn_Cancel)
        resume_btn = msg.addButton("Resume", Qt.MsgRole_ActionRole)
        
        msg.addButton("Overwrite All", Qt.MsgRole_ActionRole)
        msg.addButton("Skip All", Qt.MsgRole_ActionRole)
        msg.addButton("Resume All", Qt.MsgRole_ActionRole)
        
        msg.exec()
        
        clicked = msg.clickedButton()
        
        if clicked == overwrite_btn:
            return "overwrite"
        elif clicked == skip_btn:
            return "skip"
        elif clicked == cancel_btn:
            return "cancel"
        elif clicked == resume_btn:
            return "resume"
        elif msg.clickedButton().text() == "Overwrite All":
            return "overwrite_all"
        elif msg.clickedButton().text() == "Skip All":
            return "skip_all"
        elif msg.clickedButton().text() == "Resume All":
            return "resume_all"
        else:
            return "cancel"
