from sftp_browserclass import Browser
from sftp_filetablemodel import FileTableModel
from sftp_sortfiltermodel import DirectoryFirstSortProxyModel
from PySide6.QtWidgets import QMessageBox, QHeaderView, QTableView, QApplication, QProgressDialog
from PySide6.QtCore import QThreadPool
from sftp_qt_compat import Qt
import os
import shutil

from sftp_creds import get_credentials, set_credentials
from sftp_transfer_handler import DeletionWorker
from sftp_preferences import get_preferences
from sftp_context_menu_customizer import is_visible

class FileBrowser(Browser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        self.init_ui()  # Initialize UI (creates self.table)
        try:
            self.model = FileTableModel(session_id)
        except (OSError, IOError, RuntimeError) as e:
            pass
        self.proxy_model = DirectoryFirstSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.table.setModel(self.proxy_model)

        prefs = get_preferences()
        col = prefs.get("sort_column", 0)
        order_str = prefs.get("sort_order", "ascending")
        order = Qt.AscendingOrder if order_str == "ascending" else Qt.DescendingOrder
        self.table.sortByColumn(col, order)

        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Prevent word-wrap causing multi-line rows
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(22)

        # Column layout: name stretches to fill, size/date are fixed, permissions hidden
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, Qt.HeaderView_Interactive)
        header.setSectionResizeMode(1, Qt.HeaderView_Interactive)
        header.setSectionResizeMode(2, Qt.HeaderView_Interactive)
        header.setSectionResizeMode(3, Qt.HeaderView_Interactive)
        header.setMinimumSectionSize(60)
        saved_widths = prefs.get("local_column_widths", [300, 90, 100, 150])
        for i, w in enumerate(saved_widths):
            if i < 4:
                self.table.setColumnWidth(i, w)
        header.hideSection(2)  # Hide Permissions by default

        # Hide permissions column by default
        self.table.setColumnHidden(2, True)

        header.sectionResized.connect(self._on_local_column_resized)
        
        # Add these lines to enable full row selection
        self.table.setSelectionBehavior(Qt.TableView_SelectRows)
        self.table.setSelectionMode(Qt.TableView_ExtendedSelection)  # Allow Ctrl+Click and Shift+Click multi-select

        # Fix tree view buttons for local browser (upload, not download)
        self.tree_download_btn.setText("⬆️ Upload")
        self.tree_download_btn.setToolTip("Upload selected directory to remote")
        self.tree_download_all_btn.setText("⬆️⬆️ Upload All")
        self.tree_download_all_btn.setToolTip("Upload all visible directories to remote")

        self.model.get_files()

        if getattr(self, '_pending_tree_populate', False):
            self._pending_tree_populate = False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.populate_tree_view)

    def _on_local_column_resized(self, logical_index, old_size, new_size):
        widths = [self.table.columnWidth(i) for i in range(4)]
        get_preferences().set("local_column_widths", widths)

    def remove_directory_with_prompt(self, local_path=None, always=0):
        self.always = always
        creds = get_credentials(self.session_id)

        # Get selected items
        current_browser = self.table
        if current_browser is None:
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

            full_path = os.path.join(creds.get('current_local_directory'), filename)
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

        # For single item, do it inline (fast, no need for background thread)
        if len(selected_paths) == 1:
            self._delete_single_item_local(selected_paths[0])
            return

        # Run batch deletion in background thread to keep UI responsive
        worker = DeletionWorker(selected_paths, is_remote=False)

        progress = QProgressDialog("Deleting files...", "Cancel", 0, len(selected_paths), self)
        progress.setWindowTitle("Delete Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # Keep references to prevent garbage collection
        self._deletion_worker = worker
        self._deletion_progress = progress

        def on_progress(idx, filename):
            if progress.wasCanceled():
                worker.cancel()
            progress.setValue(idx)
            progress.setLabelText(f"Deleting: {filename}")

        def on_finished(success_count, failure_count, failures):
            progress.close()
            self._deletion_worker = None
            self._deletion_progress = None

            if len(selected_paths) > 1:
                summary_parts = []
                if success_count > 0:
                    summary_parts.append(f"{success_count} deleted successfully")
                if failure_count > 0:
                    summary_parts.append(f"{failure_count} failed")
                summary_msg = ", ".join(summary_parts)

                if failure_count > 0 and len(failures) <= 3:
                    summary_msg += "\n\nFailed items:"
                    for path, error in failures[:3]:
                        summary_msg += f"\n• {os.path.basename(path)}: {error}"
                    if len(failures) > 3:
                        summary_msg += f"\n...and {len(failures) - 3} more"

                QMessageBox.information(self, "Delete Complete", summary_msg)

            self.model.get_files()
            self.notify_observers()

        worker.signals.progress.connect(on_progress)
        worker.signals.finished.connect(on_finished)

        QThreadPool.globalInstance().start(worker)
        self.message_signal.emit(f"Deleting {len(selected_paths)} items...")

    def _delete_single_item_local(self, path):
        """Delete a single local item synchronously (for single-item deletes)"""
        try:
            if not os.path.exists(path):
                self.message_signal.emit("File not found.")
                return

            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path)

            self.message_signal.emit("Deleted successfully.")
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Delete failed: {e}")

        self.model.get_files()
        self.notify_observers()

    def is_remote_browser(self):
        return False

    def rename(self, old_path, new_name):
        """Rename a local file or directory"""
        try:
            if not os.path.exists(old_path):
                self.message_signal.emit(f"Path '{old_path}' not found.")
                return False
            
            parent = os.path.dirname(old_path)
            new_path = os.path.join(parent, new_name)
            
            if os.path.exists(new_path):
                self.message_signal.emit(f"A file or directory named '{new_name}' already exists.")
                return False
            
            os.rename(old_path, new_path)
            self.message_signal.emit(f"Renamed to: {new_name}")
            self.model.get_files()
            self.notify_observers()
            return True
        except (OSError, IOError) as e:
            self.message_signal.emit(f"Error renaming: {e}")
            return False

    def get_current_directory(self):
        """Get the current local directory"""
        creds = get_credentials(self.session_id)
        return creds.get('current_local_directory', '.')

    def navigate_to_bookmark(self, path):
        """Navigate to a bookmarked local directory"""
        try:
            if os.path.exists(path) and os.path.isdir(path):
                set_credentials(self.session_id, 'current_local_directory', path)
                os.chdir(path)
                self.model.get_files()
                self.notify_observers()
                self.message_signal.emit(f"Navigated to: {path}")
                return True
            else:
                self.message_signal.emit(f"Bookmark path not found: {path}")
                return False
        except (OSError, IOError, RuntimeError) as e:
            self.message_signal.emit(f"Error navigating to bookmark: {e}")
            return False

    def populate_tree_view(self):
        """Build tree starting from current directory as root"""
        from PySide6.QtWidgets import QTreeWidgetItem
        
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory', os.getcwd())
        
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
        from PySide6.QtWidgets import QTreeWidgetItem
        
        self.tree_widget.clear()
        
        try:
            # Create root item
            root_item = QTreeWidgetItem(self.tree_widget)
            root_name = os.path.basename(root_path) or root_path
            root_item.setText(0, "📁 " + root_name)
            root_item.setData(0, Qt.UserRole, {'path': root_path, 'is_dir': True, 'is_root': True})
            root_item.setExpanded(True)
            
            # If current is same as root, highlight it
            if os.path.normpath(root_path) == os.path.normpath(current_path):
                self._mark_current_item(root_item)
            
            # Populate subdirectories lazily
            self._populate_tree_children(root_item, root_path)
            
            # Expand path to current directory if it's a subdirectory
            if current_path.startswith(root_path) and current_path != root_path:
                self._expand_to_path(root_item, root_path, current_path)
            
        except (OSError, IOError, RuntimeError) as e:
            self.tree_status_label.setText(f"Error: {e}")
    
    def _populate_tree_children(self, parent_item, path):
        """Populate tree with subdirectories of the given path (lazy loading)"""
        from PySide6.QtWidgets import QTreeWidgetItem, QApplication
        
        item_count = 0
        
        try:
            if not os.path.isdir(path):
                self.tree_status_label.setText(f"❌ Not a directory: {path}")
                return 0
            
            # Show loading feedback
            self.tree_status_label.setText(f"⏳ Loading {path}...")
            QApplication.processEvents()
            
            entries = list(os.scandir(path))
            
            if not entries:
                self.tree_status_label.setText(f"📂 {path} (empty)")
                return 0
            
            # Filter and sort only directories
            dirs = []
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(entry)
                except (OSError, PermissionError):
                    continue
            
            dirs.sort(key=lambda x: x.name.lower())
            
            for entry in dirs:
                child_item = QTreeWidgetItem(parent_item)
                child_item.setText(0, "📁 " + entry.name)
                child_item.setData(0, Qt.UserRole, {'path': entry.path, 'is_dir': True, 'is_root': False})
                
                # Add placeholder for lazy loading - this allows expansion
                dummy_child = QTreeWidgetItem(child_item)
                dummy_child.setText(0, "⏳ Loading...")
                
                item_count += 1
            
            # Refresh tree to show newly added items
            self.tree_widget.update()
        
        except (OSError, IOError, RuntimeError) as e:
            self.tree_status_label.setText(f"❌ Error: {str(e)[:50]}")
            return 0
        
        # Update status with success message
        if item_count == 0:
            self.tree_status_label.setText(f"📂 {path} (no subdirectories)")
        else:
            self.tree_status_label.setText(f"✅ {path} - {item_count} subdirectories")
        
        return item_count
    
    def _expand_to_path(self, parent_item, parent_path, target_path):
        """Expand tree to show target_path and mark it as current"""
        
        try:
            # Get relative path from parent to target
            rel_path = os.path.relpath(target_path, parent_path)
            if rel_path.startswith('..'):
                return  # Target is not under parent
            
            path_parts = rel_path.split(os.sep)
            current_item = parent_item
            current_path = parent_path
            
            for part in path_parts:
                if not part:
                    continue
                
                # Find child with this name
                found = False
                for i in range(current_item.childCount()):
                    child = current_item.child(i)
                    child_name = child.text(0).replace("📁 ", "").replace("🎯 ", "")
                    if child_name == part:
                        # Remove placeholder and load children (check with "in" to handle emoji prefixes)
                        if child.childCount() > 0 and "Loading..." in child.child(0).text(0):
                            child.removeChild(child.child(0))
                            child_path = os.path.join(current_path, part)
                            self._populate_tree_children(child, child_path)
                        
                        child.setExpanded(True)
                        current_item = child
                        current_path = os.path.join(current_path, part)
                        found = True
                        break
                
                if not found:
                    break
            
            # Mark the final item as current
            self._mark_current_item(current_item)
            self.tree_widget.scrollToItem(current_item)
            
        except (OSError, IOError, RuntimeError) as e:
            pass
    def _mark_current_item(self, item):
        """Mark an item as the current directory"""
        # Remove bold from all items
        self._clear_current_marks(self.tree_widget.invisibleRootItem())
        
        # Mark this item as current
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setText(0, "🎯 " + item.text(0).replace("📁 ", "").replace("🎯 ", ""))
        item.setData(0, Qt.UserRole + 1, True)  # Mark as current
    
    def _clear_current_marks(self, parent_item):
        """Clear current marks from all items"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            font = child.font(0)
            font.setBold(False)
            child.setFont(0, font)
            child.setText(0, "📁 " + child.text(0).replace("📁 ", "").replace("🎯 ", ""))
            child.setData(0, Qt.UserRole + 1, False)
            self._clear_current_marks(child)
    
    def tree_item_expanded_handler(self, item):
        """Handle item expansion - lazy load subdirectories"""
        
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        path = data.get('path')
        is_dir = data.get('is_dir', False)
        
        if is_dir and item.childCount() > 0:
            first_child = item.child(0)
            # Check for placeholder (with or without emoji prefix)
            if "Loading..." in first_child.text(0):
                item.removeChild(first_child)
                self._populate_tree_children(item, path)
    
    def tree_double_click_handler(self, item, column):
        """Handle double-click - navigate to directory"""
        
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        
        path = data.get('path')
        is_dir = data.get('is_dir', False)
        
        if is_dir and os.path.isdir(path):
            # Navigate to this directory
            set_credentials(self.session_id, 'current_local_directory', path)
            os.chdir(path)
            self.model.get_files()
            self.notify_observers()
            self.message_signal.emit(f"Changed to: {path}")
            
            # Update tree current marker without rebuilding
            self._tree_current_path = path
            self._mark_current_item(item)
            self.tree_path_input.setText(path)
    
    def tree_go_up(self):
        """Navigate to parent directory and make it the new root"""
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory', os.getcwd())
        parent_dir = os.path.dirname(current_dir)
        
        if parent_dir and parent_dir != current_dir:
            # Navigate up
            set_credentials(self.session_id, 'current_local_directory', parent_dir)
            os.chdir(parent_dir)
            self.model.get_files()
            self.notify_observers()
            self.message_signal.emit(f"Changed to: {parent_dir}")
            
            # Rebuild tree with new root
            self.populate_tree_view()
        else:
            # At filesystem root
            self.message_signal.emit("Already at root directory")
    
    def tree_path_navigate(self):
        """Navigate to path entered in tree path input"""
        path = self.tree_path_input.text().strip()
        
        if not path:
            return
        
        # Expand ~ to home directory
        if path.startswith('~'):
            path = os.path.expanduser(path)
        
        # Make absolute if relative
        if not os.path.isabs(path):
            creds = get_credentials(self.session_id)
            current_dir = creds.get('current_local_directory', os.getcwd())
            path = os.path.join(current_dir, path)
        
        # Normalize path
        path = os.path.normpath(path)
        
        if not os.path.exists(path):
            self.tree_status_label.setText(f"❌ Path does not exist: {path}")
            return
        
        if not os.path.isdir(path):
            self.tree_status_label.setText(f"❌ Not a directory: {path}")
            return
        
        # Navigate to the path
        set_credentials(self.session_id, 'current_local_directory', path)
        os.chdir(path)
        self.model.get_files()
        self.notify_observers()
        self.message_signal.emit(f"Changed to: {path}")
        
        # Rebuild tree with new root
        self.populate_tree_view()

    def tree_download_selected(self):
        """Upload selected local directory to remote"""
        
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

        if not is_dir or not os.path.isdir(path):
            self.tree_status_label.setText("❌ Selected item is not a directory")
            return

        # Get remote credentials
        creds = get_credentials(self.session_id)
        remote_dir = creds.get('current_remote_directory', '/')

        # Upload the directory
        self.message_signal.emit(f"⬆️ Queuing upload: {path} -> {remote_dir}")
        self.upload_directory(path, remote_dir)

    def tree_download_all(self):
        """Upload all visible local directories to remote"""
        
        # Get root item
        root = self.tree_widget.invisibleRootItem()
        if root.childCount() == 0:
            self.tree_status_label.setText("❌ No directories to upload")
            return

        # Get remote credentials
        creds = get_credentials(self.session_id)
        remote_dir = creds.get('current_remote_directory', '/')

        # Count directories to upload
        upload_count = 0
        for i in range(root.child(0).childCount()):
            item = root.child(0).child(i)
            data = item.data(0, Qt.UserRole)
            if data and data.get('is_dir', False):
                path = data.get('path')
                if os.path.isdir(path):
                    self.message_signal.emit(f"⬆️ Queuing upload: {path} -> {remote_dir}")
                    self.upload_directory(path, remote_dir)
                    upload_count += 1

        if upload_count > 0:
            self.tree_status_label.setText(f"✅ Queued {upload_count} directories for upload")
        else:
            self.tree_status_label.setText("❌ No directories to upload")

    def tree_delete_selected(self):
        """Delete selected local directory"""
        from PySide6.QtWidgets import QMessageBox
        import shutil

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

        if not is_dir or not os.path.isdir(path):
            self.tree_status_label.setText("❌ Selected item is not a directory")
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self, 'Confirm Delete',
            f"Are you sure you want to delete the directory:\n\n{path}\n\nThis action cannot be undone!",
            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
            Qt.MsgBtn_No
        )

        if reply != Qt.MsgBtn_Yes:
            return

        try:
            # Remove the directory
            shutil.rmtree(path)
            self.message_signal.emit(f"🗑️ Deleted: {path}")
            self.tree_status_label.setText(f"✅ Deleted: {os.path.basename(path)}")
            
            # Refresh tree view
            self.populate_tree_view()
            
            # Refresh file table
            self.model.get_files()
            self.notify_observers()
        except (OSError, IOError, RuntimeError) as e:
            self.tree_status_label.setText(f"❌ Error deleting: {str(e)[:50]}")
            QMessageBox.critical(self, "Error", f"Failed to delete directory:\n{str(e)}")

    def _update_tree_up_button(self):
        """Update up button state based on current directory"""
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory', os.getcwd())
        parent_dir = os.path.dirname(current_dir)
        
        # Disable if at filesystem root
        self.tree_up_btn.setEnabled(parent_dir != current_dir)
    
    def _get_local_tree_menu_config(self):
        prefs = get_preferences()
        items = prefs.get('context_menu_items', {}).get('local_tree')
        if not items:
            from sftp_preferences import DEFAULT_PREFERENCES
            items = DEFAULT_PREFERENCES.get('context_menu_items', {}).get('local_tree', [])
        return items

    def populate_tree_context_menu(self, menu, pos, item):
        """Populate the local tree context menu."""
        items = self._get_local_tree_menu_config()

        if not item:
            refresh_action = menu.addAction("🔄 Refresh Tree")
            refresh_action.triggered.connect(self.populate_tree_view)
            return

        data = item.data(0, Qt.UserRole)
        if not data:
            return

        path = data.get('path')
        is_root = data.get('is_root', False)

        if not is_root:
            if is_visible(items, 'open'):
                open_action = menu.addAction("📂 Open")
                open_action.triggered.connect(lambda: self.tree_open_handler(path, item))

        if is_visible(items, 'refresh'):
            refresh_action = menu.addAction("🔄 Refresh")
            refresh_action.triggered.connect(self.populate_tree_view)

        if not is_root:
            menu.addSeparator()
            if is_visible(items, 'upload_directory'):
                upload_action = menu.addAction("⬆️ Upload Directory")
                upload_action.triggered.connect(self.tree_download_selected)

            if is_visible(items, 'delete'):
                delete_action = menu.addAction("🗑️ Delete")
                delete_action.triggered.connect(lambda: self.tree_delete_selected())

        self.add_custom_tree_context_menu_actions(menu, pos, item)

    def tree_open_handler(self, path, item):
        """Handle opening a directory from the tree."""
        if os.path.isdir(path):
            set_credentials(self.session_id, 'current_local_directory', path)
            os.chdir(path)
            self.model.get_files()
            self.notify_observers()
            self.message_signal.emit(f"Changed to: {path}")
            self._tree_current_path = path
            self._mark_current_item(item)
            self.tree_path_input.setText(path)
