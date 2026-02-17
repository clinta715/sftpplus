# SFTP Client Interface Redesign Plan

## Completed Phases

### Phase 1: Integrate Transfer Queue ✅ COMPLETED
**Date:** 2026-02-08

**Changes Made:**
- Created `sftp_transfer_queue_widget.py` with `TransferQueueWidget` class
- Widget inherits from `QWidget` instead of `QMainWindow`
- Added as permanent first tab ("📋 Transfers")
- Removed separate Transfer Queue window
- Updated `sftp.py` to use new widget

**Files Modified:**
- `sftp.py` - Import changes, tab creation, cleanup
- `sftp_transfer_queue_widget.py` - NEW FILE (755 lines)

**Files Removed:**
- None (kept backward compatibility with `sftp_backgroundthreadwindow.py`)

### Phase 2: Integrate Site Manager (Connections) ✅ COMPLETED
**Date:** 2026-02-08

**Changes Made:**
- Created `sftp_connections_widget.py` with `ConnectionsWidget` class
- Widget inherits from `QWidget` instead of `QDialog`
- Added as permanent second tab ("🔗 Connections")
- "Edit Host Data" button now switches to Connections tab
- Connection requests automatically connect and switch to connection form
- Same functionality as HostDataEditor but embedded

**Files Modified:**
- `sftp.py` - Import changes, tab creation, signal handling
- `sftp_connections_widget.py` - NEW FILE (~400 lines)

**Files Removed:**
- None (kept backward compatibility with `sftp_hostdataeditor.py`)

### Phase 3: Improved File Browser Layout ✅ COMPLETED
**Date:** 2026-02-08

**Changes Made:**
- Created `sftp_file_browser_panel.py` with `FileBrowserPanel` class
- Collapsible local browser panel with toggle button
- QSplitter for resizable panels
- Toolbar with labels and toggle
- Cleaner, more responsive layout

**Features:**
- Toggle button (◀/▶) to show/hide local browser
- QSplitter allows dragging to resize panels
- Labels for "Local Files" and "Remote Files"
- Consistent styling with application theme

**Files Modified:**
- `sftp.py` - Use FileBrowserPanel instead of separate browsers
- `sftp_file_browser_panel.py` - NEW FILE (~200 lines)

### Phase 4: Optional Future Enhancements

**Planned features:**
- Add Console/Logs tab
- Dark mode support
- Custom themes
- Keyboard shortcut customization
- Session state saving/restoring
- Multi-monitor support

## Implementation Strategy

### Phase 1: Integrate Transfer Queue
1. Convert `BackgroundThreadWindow` from `QMainWindow` to `QWidget`
2. Create tab in main window for transfers
3. Remove separate transfer window
4. Update all references to use tab instead

### Phase 2: Integrate Site Manager  
1. Convert `HostDataEditor` from `QDialog` to `QWidget`
2. Create tab in main window for connections
3. Add "New Tab from Connection" feature
4. Remove modal dialog behavior

### Phase 3: Improve File Browser Layout
1. Make local browser collapsible (hide/show button)
2. Add split pane divider
3. Improve drag-and-drop visual feedback
4. Add breadcrumb navigation

### Phase 4: Add Docking Support (Optional)
1. Use `QDockWidget` for panels
2. Allow users to rearrange layout
3. Save/restore window state
4. Support multiple monitors

## Benefits

1. **Single Window:** No more lost windows or window management
2. **Better Workflow:** Everything accessible via tabs
3. **Cleaner Interface:** Organized by function
4. **Consistent UX:** All features in one place
5. **Easier to Maintain:** Less window management code
6. **Better Performance:** Single event loop, shared resources

## Technical Considerations

1. **State Management:** Need to track active tab and restore on restart
2. **Tab Persistence:** Remember which tabs were open
3. **Keyboard Shortcuts:** Add shortcuts for tab switching (Ctrl+1, Ctrl+2, etc.)
4. **Responsive Layout:** Ensure it works on smaller screens
5. **Session Management:** Handle multiple connection tabs cleanly

## Migration Path

1. Keep existing code functional during transition
2. Create new integrated layout in parallel
3. Feature flags to toggle between old/new
4. Gradually deprecate separate windows
5. Remove old window code once stable

## UI Components Needed

1. `IntegratedMainWindow` - New main window class
2. `TransferQueueWidget` - Converted from window
3. `ConnectionsWidget` - Converted from dialog
4. `FileBrowserPanel` - Enhanced file browser
5. `ConsoleWidget` - Log/console view
6. `TabManager` - Handle tab creation/switching

## Questions to Resolve

1. Should transfers be a tab or a persistent bottom panel?
2. Should site manager open as tab or overlay?
3. Do we need a sidebar or just tabs?
4. Should file browsers be in tabs or main area?
5. How to handle multiple concurrent connections?
6. Mobile/tablet support considerations?

## Next Steps

1. Create mockups/wireframes
2. Decide on final layout approach
3. Create feature branch for development
4. Implement Phase 1 (Transfer Queue integration)
5. Test and gather feedback
6. Proceed to Phase 2
7. Iterate based on usage

## Design Principles

1. **Progressive Disclosure:** Show advanced features only when needed
2. **Consistency:** Same patterns throughout UI
3. **Efficiency:** Minimize clicks for common tasks
4. **Feedback:** Clear visual indicators for operations
5. **Flexibility:** Allow customization of layout
6. **Simplicity:** Don't overwhelm new users

## Files to Modify

- `sftp.py` - Main window restructuring
- `sftp_backgroundthreadwindow.py` - Convert to widget
- `sftp_hostdataeditor.py` - Convert to widget
- `sftp_remotefilebrowserclass.py` - Layout improvements
- `sftp_browserclass.py` - Layout improvements

## New Files to Create

- `sftp_integrated_main.py` - New main window (optional gradual approach)
- `sftp_tab_widget.py` - Tab management
- `sftp_sidebar.py` - Sidebar navigation (if using sidebar design)
- `sftp_console_widget.py` - Console/log widget

## Testing Checklist

- [ ] All existing features work in new layout
- [ ] Transfers display correctly
- [ ] Site manager functions properly
- [ ] File browsers work as expected
- [ ] Multiple connections handled correctly
- [ ] Window state saves and restores
- [ ] Keyboard shortcuts functional
- [ ] Performance is acceptable
- [ ] UI is responsive on different screen sizes
- [ ] No memory leaks or resource issues

## Future Enhancements

1. Dark mode support
2. Custom themes
3. Keyboard shortcut customization
4. Scripting/automation panel
5. SFTP session logging
6. Bandwidth monitoring graphs
7. Transfer scheduling
8. Sync functionality
9. Multi-server operations
10. Plugin architecture
