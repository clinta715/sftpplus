# Multi-threaded SFTP Client

A multi-tabbed, ephemeral-connection based graphical SFTP client written in Python and Qt5.

## Features

- **Multi-tabbed interface**: Connect to multiple SFTP servers simultaneously
- **Ephemeral connections**: Each operation creates a fresh connection for security
- **Threaded operations**: Uploads/downloads run in background threads
- **Dual-pane interface**: Local and remote file browsers side-by-side
- **Progress tracking**: Real-time progress indicators for file transfers
- **Queue management**: Cancelable transfer operations

## Requirements

- Python 3.7+
- PyQt5
- paramiko
- icecream (for debugging)
- cryptography

## Installation

```bash
pip install PyQt5 paramiko icecream cryptography
```

## Usage

### Basic Operations

1. **Connect to server**:
   - Enter hostname/IP, username, password, and optionally port (default: 22)
   - Press Enter in password or port field to connect
   - Additional connections open in new tabs

2. **File operations**:
   - **Right-click**: Context menu for upload/download operations
   - **Double-click remote file**: Download and prompt for save location
   - **Double-click remote directory**: Navigate into directory
   - **Drag & drop**: Supported between local and remote panes

3. **Navigation**:
   - Use `..` to navigate up directory levels
   - Path is maintained separately for each tab

### Keyboard Shortcuts

- `Enter`: Connect/Confirm action
- `Esc`: Cancel current operation
- `Ctrl+R`: Refresh current directory view

## Architecture

### Core Components

- **sftp.py**: Main application window and orchestration logic
- **sftp_browserclass.py**: Local file browser implementation
- **sftp_remotefilebrowserclass.py**: Remote SFTP browser implementation
- **sftp_downloadworkerclass.py**: Background transfer worker threads
- **sftp_backgroundthreadwindow.py**: Command execution and response handling
- **sftp_creds.py**: Session credential management
- **sftp_hostdataeditor.py**: Connection data storage and encryption
- **sftp_filetablemodel.py** / **sftp_remotefiletablemodel.py**: Data models for file listings

### Connection Model

The application uses an **ephemeral connection pattern**:
1. Each SFTP operation creates a fresh SSH connection
2. Commands are queued with unique IDs
3. Background thread executes commands sequentially
4. Connections are closed after each operation
5. Response queues return results to the appropriate UI component

### Security Considerations

⚠️ **Security Note**: Current implementation has several security issues that should be addressed:

- Credentials stored with weak encryption
- Base64 encoding used for password "encryption" in some places
- SSH host key verification disabled
- Error messages may expose sensitive information

### Known Issues

- **Resource leaks**: Some error paths don't properly clean up SSH connections
- **Performance**: Uses polling loops instead of proper event-driven architecture
- **Exception handling**: Many overly broad exception handlers that hide errors
- **Memory management**: Response queues may accumulate without proper cleanup

## Development History

### Recent Updates

**7/29/25**: Code review and security audit identified critical issues:
- Exception handling patterns need improvement
- Security vulnerabilities in credential storage
- Performance issues with polling mechanisms
- Resource management problems

**1/14/25**: Experimented with DeepSeek V3 models for coding assistance via Aider. Found comparable performance to Claude Sonnet 3.5 at significantly lower cost.

### Development Approach

This project was not auto-generated with templates. Instead:
1. LLM crafted individual functions
2. Manual integration and refactoring for consistent structure
3. Split from monolithic file into modular OOP hierarchy
4. Enhanced collaboration with LLMs through better organization

### Design Reflections

**What worked well**:
- Proper OOP hierarchical design achieved learning objectives
- Modular structure enables easier maintenance and LLM collaboration
- Ephemeral connection model provides good security separation

**What could be improved**:
- GUI complexity due to excessive class separation
- Would benefit from QT Creator for UI design
- Could consolidate main window GUI components into single class

## Contributing

### Code Quality Priorities

1. **Fix security vulnerabilities** - Use system keychain for credential storage
2. **Improve exception handling** - Replace broad catches with specific exceptions
3. **Add proper resource cleanup** - Use context managers for SSH connections
4. **Implement proper logging** - Replace debugging output with structured logging
5. **Add test coverage** - Currently no automated tests exist

### Development Tools

- **Aider**: For AI-assisted development
- **DeepSeek V3**: Cost-effective coding assistance
- **Claude Sonnet**: High-quality code review and debugging
# sftpplus
