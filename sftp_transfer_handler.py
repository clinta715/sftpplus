from PyQt6.QtWidgets import QInputDialog, QMessageBox
from sftp_qt_compat import Qt
from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import add_sftp_job
from sftp_preferences import get_preferences
import os
import stat
from icecream import ic


class TransferHandlerMixin:
    """Mixin class providing file transfer functionality.
    
    This class handles:
    - Directory traversal and batch transfers
    - Overwrite prompts and conflict resolution
    """

    transfer_started = None

    def _get_transfer_action(self, target_path, skip_all, overwrite_all, resume_all, is_directory=False):
        """Determine the transfer action based on user choice and flags."""
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
        """Ensure a directory exists, creating it if necessary."""
        if is_remote:
            if not self.sftp_exists(directory_path):
                # We need to handle nested directories
                parts = directory_path.strip('/').split('/')
                current = ""
                for part in parts:
                    current += '/' + part
                    if not self.sftp_exists(current):
                        self.sftp_mkdir(current)
        else:
            os.makedirs(directory_path, exist_ok=True)

    def traverse_and_transfer(self, source_dir, dest_dir, is_source_remote, is_dest_remote,
                              skip_all=False, overwrite_all=False, resume_all=False,
                              always=0, is_top_level=True):
        """Traverse a directory and transfer all files recursively.
        
        Args:
            source_dir: Source directory path
            dest_dir: Destination directory path
            is_source_remote: Whether source is remote
            is_dest_remote: Whether destination is remote
            skip_all: Skip all conflicts
            overwrite_all: Overwrite all conflicts
            resume_all: Resume all transfers
            always: Recursive depth tracker
            is_top_level: Whether this is the initial call
        """
        creds = get_credentials(self.session_id)
        
        # Ensure destination exists
        self._ensure_directory_exists(dest_dir, is_remote=is_dest_remote)
        
        if is_source_remote:
            files = self.sftp_listdir_attr(source_dir)
        else:
            files = os.listdir(source_dir)
            
        for entry in files:
            if is_source_remote:
                filename = entry.filename
                # Skip . and ..
                if filename in ['.', '..']:
                    continue
                is_dir = stat.S_ISDIR(entry.st_mode)
            else:
                filename = entry
                if filename in ['.', '..']:
                    continue
                is_dir = os.path.isdir(os.path.join(source_dir, filename))
                
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(dest_dir, filename)
            
            if is_dir:
                # Recurse into directory
                skip_all, overwrite_all, resume_all = self.traverse_and_transfer(
                    source_path, dest_path,
                    is_source_remote, is_dest_remote,
                    skip_all, overwrite_all, resume_all,
                    always + 1, is_top_level=False
                )
                continue
                
            # Handle file conflict
            exists = self.sftp_exists(dest_path) if is_dest_remote else os.path.exists(dest_path)
            
            command = "upload" if is_dest_remote else "download"
            
            if exists and not skip_all and not overwrite_all and not resume_all:
                action = self.prompt_overwrite(dest_path)
                if action == "cancel":
                    return skip_all, overwrite_all, resume_all
                elif action == "skip":
                    continue
                elif action == "skip_all":
                    skip_all = True
                    continue
                elif action == "overwrite_all":
                    overwrite_all = True
                elif action == "resume_all":
                    resume_all = True
                elif action == "resume":
                    command = "resume"
                # If action is 'overwrite', we proceed with default command
                    
            if skip_all:
                continue
            
            if resume_all:
                command = "resume"
                
            job_id = create_random_integer()
            
            add_sftp_job(source_path, is_source_remote, dest_path, is_dest_remote,
                        creds.get('hostname', ''),
                        creds.get('username', ''),
                        creds.get('password', ''),
                        creds.get('port', 22),
                        command, job_id, creds.get('key'))
                            
            if self.transfer_started:
                self.transfer_started.emit(str(job_id))
        
        return skip_all, overwrite_all, resume_all

    def upload_directory(self, source_directory, destination_directory, 
                         skip_all=False, overwrite_all=False, resume_all=False):
        """Upload a directory to remote server."""
        self.traverse_and_transfer(
            source_directory, destination_directory,
            is_source_remote=False, is_dest_remote=True,
            skip_all=skip_all, overwrite_all=overwrite_all, resume_all=resume_all
        )
        self.message_signal.emit(f"Directory upload started: {source_directory}")

    def prompt_overwrite(self, item_path):
        """Prompt user for overwrite action."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon_Question)
        msg.setText(f"File already exists:\n{item_path}")
        msg.setWindowTitle("File Exists")
        
        overwrite_btn = msg.addButton("Overwrite", QMessageBox.ButtonRole.ActionRole)
        skip_btn = msg.addButton("Skip", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg.addButton(QMessageBox.StandardButton.Cancel)
        resume_btn = msg.addButton("Resume", QMessageBox.ButtonRole.ActionRole)
        
        overwrite_all_btn = msg.addButton("Overwrite All", QMessageBox.ButtonRole.ActionRole)
        skip_all_btn = msg.addButton("Skip All", QMessageBox.ButtonRole.ActionRole)
        resume_all_btn = msg.addButton("Resume All", QMessageBox.ButtonRole.ActionRole)
        
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
        elif clicked == overwrite_all_btn:
            return "overwrite_all"
        elif clicked == skip_all_btn:
            return "skip_all"
        elif clicked == resume_all_btn:
            return "resume_all"
        else:
            return "cancel"
