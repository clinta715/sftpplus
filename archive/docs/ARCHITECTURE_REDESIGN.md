# SFTP Client Architecture Redesign Proposal

## Current Design (Problematic)

```
UI Layer
    ↓ (11 positional args)
add_sftp_job(source, is_src_remote, dest, is_dst_remote, 
             hostname, username, password, port, command, job_id, key)
    ↓
SFTPJob Object
    ↓
Queue (global)
    ↓
DownloadWorker
    ↓
Global creds store (sftp_current_creds)
```

### Issues:
1. 11 parameters easy to get wrong
2. Credentials duplicated in every job
3. No session isolation
4. Blocking waits instead of proper async
5. Global state hard to test/debug

---

## Proposed Design: Session-Based Command Pattern

```
Session Manager
    ├── Creates isolated sessions
    ├── Stores credentials per session
    └── Manages connection pool per session

UI Layer
    ↓
session.execute(Command)
    ↓
Command Queue (per session)
    ↓
Worker Pool (per session)
    ↓
Proper async/await
```

---

## Implementation Plan

### Phase 1: Session-Based Credentials

```python
# Instead of global sftp_current_creds
class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.credentials: SFTPCredentials
        self.connection_pool: ConnectionPool
        self.job_queue: queue.Queue
        self.response_queues: Dict[str, queue.Queue]

class SFTPCredentials:
    hostname: str
    username: str
    password: Optional[str]
    port: int
    key_path: Optional[str]
    remote_directory: Optional[str]
    local_directory: Optional[str]
```

### Phase 2: Typed Command Objects

```python
from dataclasses import dataclass
from enum import Enum

class CommandType(Enum):
    DOWNLOAD = "download"
    UPLOAD = "upload"
    LIST = "list"
    STAT = "stat"
    MKDIR = "mkdir"
    RMDIR = "rmdir"
    REMOVE = "remove"
    CHDIR = "chdir"

@dataclass
class SFTPCommand:
    """Base command class - all commands inherit from this"""
    command_type: CommandType
    source_path: Optional[str] = None
    destination_path: Optional[str] = None
    local_path: Optional[str] = None
    remote_path: Optional[str] = None
    options: Optional[dict] = None  # For resume, overwrite, etc.

@dataclass
class DownloadCommand(SFTPCommand):
    """Download file from remote to local"""
    remote_path: str
    local_path: str
    resume: bool = False
    
    def validate(self) -> bool:
        if not self.remote_path:
            raise ValueError("remote_path required for download")
        if not self.local_path:
            raise ValueError("local_path required for download")
        return True

@dataclass
class UploadCommand(SFTPCommand):
    """Upload file from local to remote"""
    local_path: str
    remote_path: str
    resume: bool = False
    
    def validate(self) -> bool:
        if not self.local_path:
            raise ValueError("local_path required for upload")
        if not self.remote_path:
            raise ValueError("remote_path required for upload")
        return True

@dataclass  
class ListCommand(SFTPCommand):
    """List remote directory contents"""
    remote_path: str
    with_attributes: bool = False

@dataclass
class StatCommand(SFTPCommand):
    """Get file attributes"""
    path: str
```

### Phase 3: Session-Based Job Execution

```python
class SFTPSession:
    def __init__(self, session_id: str, credentials: SFTPCredentials):
        self.session_id = session_id
        self.credentials = credentials
        self.connection_pool = ConnectionPool()
        self.job_queue: queue.Queue = queue.Queue()
        self.response_queues: Dict[str, queue.Queue] = {}
        self.active_transfers: Dict[str, Transfer] = {}
        self._lock = threading.Lock()
    
    def execute(self, command: SFTPCommand) -> str:
        """Execute a command and return job_id"""
        job_id = self._generate_job_id()
        
        # Validate command
        if hasattr(command, 'validate'):
            command.validate()
        
        # Store response queue
        self.response_queues[job_id] = queue.Queue()
        
        # Create job
        job = SFTPJob(
            session_id=self.session_id,
            command=command,
            job_id=job_id
        )
        
        # Add to queue
        self.job_queue.put(job)
        
        return job_id
    
    def wait_for_result(self, job_id: str, timeout: float = 30.0) -> CommandResult:
        """Wait for command result"""
        if job_id not in self.response_queues:
            raise ValueError(f"Unknown job_id: {job_id}")
        
        queue = self.response_queues[job_id]
        
        try:
            result = queue.get(timeout=timeout)
            return result
        except queue.Empty:
            raise TimeoutError(f"Job {job_id} timed out")

@dataclass
class CommandResult:
    """Result of a command execution"""
    success: bool
    job_id: str
    data: Optional[Any] = None
    error: Optional[str] = None

class SFTPJob:
    """Job to be executed by worker"""
    def __init__(self, session_id: str, command: SFTPCommand, job_id: str):
        self.session_id = session_id
        self.command = command
        self.job_id = job_id
        self.timestamp = time.time()
```

### Phase 4: Clean API for UI

```python
# Instead of the current messy API:
# add_sftp_job(src, is_src, dst, is_dst, host, user, pass, port, cmd, id, key)

# New clean API:
session = session_manager.create_session(credentials)

# Download
job_id = session.download(
    remote_path="/mnt/data/file.csv",
    local_path="/Users/clint/file.csv",
    resume=False
)
result = session.wait_for_result(job_id)

# Upload  
job_id = session.upload(
    local_path="/Users/clint/file.csv",
    remote_path="/mnt/data/file.csv"
)

# List directory
job_id = session.list("/mnt/data/")
files = session.wait_for_result(job_id).data

# With async/await alternative:
result = await session.download_async(remote, local)
```

### Phase 5: Connection Pool Management

```python
class ConnectionPool:
    """Manage SSH/SFTP connections per session"""
    
    def __init__(self, max_connections: int = 5):
        self.max_connections = max_connections
        self._pool: Dict[str, SSHConnection] = {}
        self._lock = threading.Lock()
    
    def get_connection(self, credentials: SFTPCredentials) -> SSHConnection:
        """Get or create connection for credentials"""
        key = self._connection_key(credentials)
        
        with self._lock:
            if key in self._pool:
                conn = self._pool[key]
                if conn.is_active():
                    return conn
                else:
                    del self._pool[key]
            
            # Create new connection
            conn = SSHConnection(credentials)
            conn.connect()
            self._pool[key] = conn
            return conn
    
    def release_connection(self, credentials: SFTPCredentials):
        """Release connection back to pool"""
        key = self._connection_key(credentials)
        # Keep in pool for reuse, or close if pool too large
    
    def close_all(self):
        """Close all pooled connections"""
        with self._lock:
            for conn in self._pool.values():
                conn.close()
            self._pool.clear()
```

---

## Migration Strategy

### Step 1: Create Session Manager
```python
session_manager = SessionManager()
```

### Step 2: Update Connection Flow
```python
# Old:
add_sftp_job(path, True, local, False, host, user, pass, port, "download", id, key)

# New:
session = session_manager.get_or_create(session_id, credentials)
job_id = session.download(remote_path, local_path)
```

### Step 3: Keep Backward Compatibility
```python
# Wrapper to maintain old API during transition
def add_sftp_job_legacy(*args, **kwargs):
    """Legacy wrapper - creates temporary session"""
    # Parse old parameters
    # Create session
    # Execute command
    pass
```

---

## Benefits of New Design

| Aspect | Old Design | New Design |
|--------|------------|------------|
| **Parameters** | 11 positional | 2-4 typed |
| **Credentials** | Global, duplicated | Per-session, isolated |
| **Error handling** | Try/catch everywhere | Validation upfront |
| **Testing** | Hard (global state) | Easy (mock sessions) |
| **Extensibility** | Hard (add parameters) | Easy (new Command classes) |
| **Async** | Blocking waits | Proper async/await |
| **Session mgmt** | Manual session_id passing | Automatic |

---

## Files to Create/Modify

### New Files:
- `sftp_session.py` - Session and SessionManager classes
- `sftp_commands.py` - Command classes (Download, Upload, etc.)
- `sftp_connection_pool.py` - Connection pooling
- `sftp_job.py` - Job and Result classes

### Modified Files:
- `sftp.py` - Use new session-based API
- `sftp_remotefilebrowserclass.py` - Use session.execute()
- `sftp_browserclass.py` - Use session.execute()
- `sftp_downloadworkerclass.py` - Refactor to use session

### Deprecated Files:
- `sftp_creds.py` - Replaced by SFTPSession.credentials
- `sftp_downloadworkerclass.py` - Core logic moved to commands

---

## Example Usage

```python
from sftp_session import SessionManager, DownloadCommand

# Create session
credentials = SFTPCredentials(
    hostname="server.com",
    username="user",
    password="pass",
    port=22
)
session = session_manager.create_session(credentials)

# Simple download
job_id = session.download(
    remote_path="/data/file.csv",
    local_path="/home/file.csv"
)
result = session.wait_for_result(job_id)
if result.success:
    print(f"Downloaded to {result.data}")
else:
    print(f"Error: {result.error}")

# Batch operations
jobs = []
jobs.append(session.list("/data/"))
jobs.append(session.list("/backup/"))
for job_id in jobs:
    result = session.wait_for_result(job_id)
    print(f"Files: {result.data}")

# Cleanup
session.close()
```

---

## Questions to Answer

1. **Should we use async/await (asyncio) or threading?**
   - Threading: Current approach, works well for moderate loads
   - asyncio: Better scalability, but requires async paramiko (asyncssh)

2. **How to handle multiple simultaneous sessions?**
   - Per-session worker pools
   - Shared global pool with session tagging

3. **Backward compatibility?**
   - Keep old API as wrapper during transition
   - Deprecate gradually

4. **Configuration?**
   - Max connections per session
   - Timeout values
   - Retry policies

5. **Monitoring?**
   - Per-session metrics
   - Transfer progress callbacks
   - Error reporting

---

## Recommendation

**Yes, re-architect.** The current design has fundamental issues:

1. **Too many parameters** - 11 args is unmanageable
2. **Global state** - Makes testing impossible
3. **Blocking waits** - Poor user experience
4. **No session concept** - Credentials mixed with operations

The new design should:
- Use **typed Command objects** instead of positional args
- Isolate **credentials per session**
- Support **async operations** with proper callbacks
- Be **testable** with mock sessions
- Be **extensible** with new command types

**Implementation time estimate:** 2-3 days for core refactor
