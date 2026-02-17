from sftp_browserclass import Browser
from sftp_filetablemodel import FileTableModel
from sftp_sortfiltermodel import DirectoryFirstSortProxyModel
from PyQt5.QtWidgets import QMessageBox, QHeaderView, QTableView, QApplication
from PyQt5.QtCore import Qt
import os 
import shutil
from icecream import ic

from sftp_creds import get_credentials, set_credentials

class FileBrowser(Browser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        try:
            self.model = FileTableModel(session_id)
        except Exception as e:
            ic(e)

        self.proxy_model = DirectoryFirstSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.table.setModel(self.proxy_model)

        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Make all columns resizable
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

        # Add these lines to enable full row selection
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)  # Allow Ctrl+Click and Shift+Click multi-select

        # Optionally, set initial column widths
        # self.table.setColumnWidth(0, 100)  # Adjust widths as needed
        # self.table.setColumnWidth(1, 50)

    def remove_directory_with_prompt(self, local_path=None, always=0):
        self.always = always
        creds = get_credentials(self.session_id)

        # for removing LOCAL directories
        if local_path is None or local_path is False:
            # current_browser = self.focusWidget()
            current_browser = self.active_table
            if current_browser is not None:
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    # Get the same row but first column (column 0)
                    first_col_index = current_index.sibling(current_index.row(), 0)
                    selected_item = current_browser.model().data(first_col_index, Qt.DisplayRole)
                    local_path = selected_item.lstrip(" 📁📄")
                    if selected_item is not None:
                        local_path = os.path.join(creds.get('current_local_directory'), selected_item.lstrip(" 📁📄"))
            else:
                return

        try:
            # Check if the path exists locally
            if not os.path.exists(local_path):
                self.message_signal.emit(f"Path '{local_path}' not found locally.")
                return

            # Check if it's a file
            if os.path.isfile(local_path):
                os.remove(local_path)
                self.message_signal.emit(f"File '{local_path}' removed successfully.")
                return

            # It's a directory, check if it has child items
            directory_contents = os.listdir(local_path)
            subdirectories = [entry for entry in directory_contents if os.path.isdir(os.path.join(local_path, entry))]
            files = [entry for entry in directory_contents if os.path.isfile(os.path.join(local_path, entry))]

            if subdirectories or files and not self.always:
                # Directory has child items, prompt for confirmation using QMessageBox
                response = QMessageBox.question(
                    None,
                    'Confirmation',
                    f"The directory '{local_path}' contains subdirectories or files. Do you want to remove them all?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                    QMessageBox.No
                )

                if response == QMessageBox.YesToAll:
                    self.always = 1

                if response == QMessageBox.No:
                    return

                # Recursively remove subdirectories
                for entry in subdirectories:
                    entry_path = os.path.join(local_path, entry)
                    self.remove_directory_with_prompt(entry_path, self.always)

                # Remove files
                for entry in files:
                    entry_path = os.path.join(local_path, entry)
                    os.remove(entry_path)

            # Remove the directory
            shutil.rmtree(local_path)
            self.model.get_files()

        except Exception as e:
            self.message_signal.emit(f"remove_directory_with_prompt() {e}")
            ic(e)

    def is_remote_browser(self):
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
        except Exception as e:
            self.message_signal.emit(f"Error navigating to bookmark: {e}")
            return False

    def populate_tree_view(self):
        """Build tree starting from current directory as root"""
        from PyQt5.QtWidgets import QTreeWidgetItem
        from PyQt5.QtCore import Qt
        
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory', os.getcwd())
        
        # Store root and current paths
        self._tree_root_path = current_dir
        self._tree_current_path = current_dir
        
        # Update UI
        self.tree_path_label.setText(f"📂 {current_dir}")
        self._update_tree_up_button()
        
        # Build tree from root
        self._build_tree_from_root(current_dir, current_dir)
    
    def _build_tree_from_root(self, root_path, current_path):
        """Build tree starting from root_path, highlighting current_path"""
        from PyQt5.QtWidgets import QTreeWidgetItem
        from PyQt5.QtCore import Qt
        
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
            
        except Exception as e:
            ic(f"Error building tree: {e}")
            self.tree_status_label.setText(f"Error: {e}")
    
    def _populate_tree_children(self, parent_item, path):
        """Populate tree with subdirectories of the given path (lazy loading)"""
        from PyQt5.QtWidgets import QTreeWidgetItem
        from PyQt5.QtCore import Qt
        
        item_count = 0
        
        try:
            if not os.path.isdir(path):
                return 0
            
            entries = list(os.scandir(path))
            
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
                dummy_child.setText(0, "Loading...")
                
                item_count += 1
            
            # Refresh tree to show newly added items
            self.tree_widget.update()
        
        except Exception as e:
            ic(f"Error populating tree children: {e}")
        
        # Update status
        if item_count == 0:
            self.tree_status_label.setText("No subdirectories")
        else:
            self.tree_status_label.setText(f"{item_count} subdirectories - Expand to explore")
        
        return item_count
    
    def _expand_to_path(self, parent_item, parent_path, target_path):
        """Expand tree to show target_path and mark it as current"""
        from PyQt5.QtCore import Qt
        
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
            
        except Exception as e:
            ic(f"Error expanding to path: {e}")
    
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
        from PyQt5.QtCore import Qt
        
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
        from PyQt5.QtCore import Qt
        
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
            self.tree_path_label.setText(f"📂 {path}")
    
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
    
    def _update_tree_up_button(self):
        """Update up button state based on current directory"""
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory', os.getcwd())
        parent_dir = os.path.dirname(current_dir)
        
        # Disable if at filesystem root
        self.tree_up_btn.setEnabled(parent_dir != current_dir)
    
    def tree_context_menu_handler(self, pos):
        """Handle context menu on tree widget"""
        from PyQt5.QtWidgets import QMenu
        from PyQt5.QtCore import Qt
        
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
            upload_action = menu.addAction("⬆️ Upload Directory")
        
        action = menu.exec_(self.tree_widget.mapToGlobal(pos))
        
        if action == open_action:
            if os.path.isdir(path):
                set_credentials(self.session_id, 'current_local_directory', path)
                os.chdir(path)
                self.model.get_files()
                self.notify_observers()
                self.message_signal.emit(f"Changed to: {path}")
                self._tree_current_path = path
                self._mark_current_item(item)
                self.tree_path_label.setText(f"📂 {path}")
        elif action == refresh_action:
            self.populate_tree_view()
        elif action == upload_action:
            self.message_signal.emit(f"Upload directory: {path}")
