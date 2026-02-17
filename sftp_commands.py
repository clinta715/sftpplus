"""
SFTP Command Classes

Typed command objects for SFTP operations.
Replaces the 11-parameter add_sftp_job() calls.
"""
from dataclasses import dataclass, field
from typing import Optional, Any, List, Dict
from enum import Enum
from icecream import ic


class CommandType(Enum):
    """Types of SFTP commands"""
    DOWNLOAD = "download"
    UPLOAD = "upload"
    LIST = "list"
    LIST_ATTR = "list_attr"
    STAT = "stat"
    MKDIR = "mkdir"
    RMDIR = "rmdir"
    REMOVE = "remove"
    CHDIR = "chdir"
    GETCWD = "getcwd"
    RESUME_DOWNLOAD = "resume_download"
    RESUME_UPLOAD = "resume_upload"
    RENAME = "rename"


@dataclass(eq=False)
class SFTPCommand:
    """Base class for all SFTP commands"""
    job_id: str = ""
    command_type: CommandType = CommandType.DOWNLOAD
    
    def validate(self) -> bool:
        """Validate command has required fields. Override in subclasses."""
        return True
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(job_id={self.job_id})"


@dataclass(eq=False)
class DownloadCommand(SFTPCommand):
    """Download a file from remote to local"""
    command_type: CommandType = CommandType.DOWNLOAD
    remote_path: str = ""
    local_path: str = ""
    resume: bool = False
    options: Optional[Dict[str, Any]] = None
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for download")
        if not self.local_path:
            raise ValueError("local_path is required for download")
        return True
    
    def __repr__(self) -> str:
        return (f"DownloadCommand(job_id={self.job_id}, "
                f"remote={self.remote_path}, local={self.local_path})")


@dataclass(eq=False)
class UploadCommand(SFTPCommand):
    """Upload a file from local to remote"""
    command_type: CommandType = CommandType.UPLOAD
    local_path: str = ""
    remote_path: str = ""
    resume: bool = False
    options: Optional[Dict[str, Any]] = None
    
    def validate(self) -> bool:
        if not self.local_path:
            raise ValueError("local_path is required for upload")
        if not self.remote_path:
            raise ValueError("remote_path is required for upload")
        return True
    
    def __repr__(self) -> str:
        return (f"UploadCommand(job_id={self.job_id}, "
                f"local={self.local_path}, remote={self.remote_path})")


@dataclass(eq=False)
class ListCommand(SFTPCommand):
    """List remote directory contents"""
    command_type: CommandType = CommandType.LIST
    remote_path: str = ""
    with_attributes: bool = False
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for list")
        return True
    
    def __repr__(self) -> str:
        return (f"ListCommand(job_id={self.job_id}, "
                f"path={self.remote_path}, attrs={self.with_attributes})")


@dataclass(eq=False)
class StatCommand(SFTPCommand):
    """Get file/directory attributes"""
    command_type: CommandType = CommandType.STAT
    path: str = ""
    
    def validate(self) -> bool:
        if not self.path:
            raise ValueError("path is required for stat")
        return True
    
    def __repr__(self) -> str:
        return f"StatCommand(job_id={self.job_id}, path={self.path})"


@dataclass(eq=False)
class MkDirCommand(SFTPCommand):
    """Create remote directory"""
    command_type: CommandType = CommandType.MKDIR
    remote_path: str = ""
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for mkdir")
        return True
    
    def __repr__(self) -> str:
        return f"MkDirCommand(job_id={self.job_id}, path={self.remote_path})"


@dataclass(eq=False)
class RmDirCommand(SFTPCommand):
    """Remove remote directory"""
    command_type: CommandType = CommandType.RMDIR
    remote_path: str = ""
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for rmdir")
        return True
    
    def __repr__(self) -> str:
        return f"RmDirCommand(job_id={self.job_id}, path={self.remote_path})"


@dataclass(eq=False)
class RemoveCommand(SFTPCommand):
    """Remove remote file"""
    command_type: CommandType = CommandType.REMOVE
    remote_path: str = ""
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for remove")
        return True
    
    def __repr__(self) -> str:
        return f"RemoveCommand(job_id={self.job_id}, path={self.remote_path})"


@dataclass(eq=False)
class RenameCommand(SFTPCommand):
    """Rename remote file or directory"""
    command_type: CommandType = CommandType.RENAME
    remote_path: str = ""
    new_name: str = ""
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for rename")
        if not self.new_name:
            raise ValueError("new_name is required for rename")
        return True
    
    def __repr__(self) -> str:
        return f"RenameCommand(job_id={self.job_id}, old={self.remote_path}, new={self.new_name})"


@dataclass(eq=False)
class ChDirCommand(SFTPCommand):
    """Change remote directory"""
    command_type: CommandType = CommandType.CHDIR  
    remote_path: str = ""
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for chdir")
        return True
    
    def __repr__(self) -> str:
        return f"ChDirCommand(job_id={self.job_id}, path={self.remote_path})"


@dataclass(eq=False)
class GetCwdCommand(SFTPCommand):
    """Get current working directory"""
    command_type: CommandType = CommandType.GETCWD
    
    def __repr__(self) -> str:
        return f"GetCwdCommand(job_id={self.job_id})"


@dataclass(eq=False)
class ResumeDownloadCommand(SFTPCommand):
    """Resume a partially downloaded file"""
    command_type: CommandType = CommandType.RESUME_DOWNLOAD
    remote_path: str = ""
    local_path: str = ""
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path is required for resume_download")
        if not self.local_path:
            raise ValueError("local_path is required for resume_download")
        return True


@dataclass(eq=False)
class ResumeUploadCommand(SFTPCommand):
    """Resume a partially uploaded file"""
    command_type: CommandType = CommandType.RESUME_UPLOAD
    local_path: str = ""
    remote_path: str = ""
    
    def validate(self) -> bool:
        if not self.local_path:
            raise ValueError("local_path is required for resume_upload")
        if not self.remote_path:
            raise ValueError("remote_path is required for resume_upload")
        return True


# Command factory for easy creation
class CommandFactory:
    """Factory for creating command objects"""
    
    @staticmethod
    def create_download(remote_path: str, local_path: str, job_id: str, 
                       resume: bool = False) -> DownloadCommand:
        """Create a download command"""
        cmd = DownloadCommand(
            job_id=job_id,
            remote_path=remote_path,
            local_path=local_path,
            resume=resume
        )
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_upload(local_path: str, remote_path: str, job_id: str,
                     resume: bool = False) -> UploadCommand:
        """Create an upload command"""
        cmd = UploadCommand(
            job_id=job_id,
            local_path=local_path,
            remote_path=remote_path,
            resume=resume
        )
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_list(remote_path: str, job_id: str, 
                    with_attrs: bool = False) -> ListCommand:
        """Create a list command"""
        cmd = ListCommand(
            job_id=job_id,
            remote_path=remote_path,
            with_attributes=with_attrs
        )
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_stat(path: str, job_id: str) -> StatCommand:
        """Create a stat command"""
        cmd = StatCommand(job_id=job_id, path=path)
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_mkdir(remote_path: str, job_id: str) -> MkDirCommand:
        """Create a mkdir command"""
        cmd = MkDirCommand(job_id=job_id, remote_path=remote_path)
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_rmdir(remote_path: str, job_id: str) -> RmDirCommand:
        """Create a rmdir command"""
        cmd = RmDirCommand(job_id=job_id, remote_path=remote_path)
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_remove(remote_path: str, job_id: str) -> RemoveCommand:
        """Create a remove command"""
        cmd = RemoveCommand(job_id=job_id, remote_path=remote_path)
        cmd.validate()
        return cmd
    
    @staticmethod
    def create_chdir(remote_path: str, job_id: str) -> ChDirCommand:
        """Create a chdir command"""
        cmd = ChDirCommand(job_id=job_id, remote_path=remote_path)
        cmd.validate()
        return cmd


# Convenience function for creating commands
def download(remote_path: str, local_path: str, job_id: str, 
           resume: bool = False) -> DownloadCommand:
    """Create a download command"""
    return CommandFactory.create_download(remote_path, local_path, job_id, resume)


def upload(local_path: str, remote_path: str, job_id: str,
          resume: bool = False) -> UploadCommand:
    """Create an upload command"""
    return CommandFactory.create_upload(local_path, remote_path, job_id, resume)


def list_dir(remote_path: str, job_id: str, 
            with_attrs: bool = False) -> ListCommand:
    """Create a list command"""
    return CommandFactory.create_list(remote_path, job_id, with_attrs)


def stat(path: str, job_id: str) -> StatCommand:
    """Create a stat command"""
    return CommandFactory.create_stat(path, job_id)


def mkdir(remote_path: str, job_id: str) -> MkDirCommand:
    """Create a mkdir command"""
    return CommandFactory.create_mkdir(remote_path, job_id)


def rmdir(remote_path: str, job_id: str) -> RmDirCommand:
    """Create a rmdir command"""
    return CommandFactory.create_rmdir(remote_path, job_id)


def remove(remote_path: str, job_id: str) -> RemoveCommand:
    """Create a remove command"""
    return CommandFactory.create_remove(remote_path, job_id)


def chdir(remote_path: str, job_id: str) -> ChDirCommand:
    """Create a chdir command"""
    return CommandFactory.create_chdir(remote_path, job_id)
