from PyQt6.QtWidgets import QMenu, QInputDialog, QMessageBox
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
from sftp_creds import get_credentials


class BrowserActionsMixin:
    """Mixin class providing browser action and UI interaction functionality.
    
    This class handles:
    - Context menu creation and handling
    - Keyboard event handling
    - Tree view toggling and population
    - Refresh actions
    """

    def context_menu_handler(self, point):
        """Show context menu at the given point.
        
        Args:
            point: The position for the context menu
        """
        index = self.table.indexAt(point)
        if not index.isValid():
            return
            
        menu = QMenu(self)
        
        menu.addAction("Open", self.double_click_handler)
        menu.addAction("Rename", self.prompt_and_rename)
        menu.addSeparator()
        menu.addAction("New Folder", self.prompt_and_create_directory)
        menu.addSeparator()
        menu.addAction("Download", self.upload_download)
        menu.addAction("Delete", self.delete_selected_items)
        menu.addSeparator()
        menu.addAction("Refresh", self.refresh_files)
        
        menu.exec(self.table.viewport().mapToGlobal(point))

    def delete_selected_items(self):
        """Delete all selected items after confirmation."""
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            self.message_signal.emit("No items selected")
            return
            
        reply = QMessageBox.question(
            self, 'Delete',
            f'Delete {len(selection)} item(s)?',
            Qt.MsgBtn_Yes | Qt.MsgBtn_No,
            Qt.MsgBtn_No
        )
        
        if reply == Qt.MsgBtn_Yes:
            for index in selection:
                filename = index.data(Qt.DisplayRole)
                creds = get_credentials(self.session_id)
                current_dir = creds.get('current_remote_directory', '/')
                full_path = self.get_normalized_remote_path(current_dir, filename)
                
                if self.is_remote_directory(full_path):
                    self.sftp_rmdir(full_path)
                else:
                    self.sftp_remove(full_path)

    def keyPressEvent(self, event):
        """Handle keyboard events.
        
        Args:
            event: The key press event
        """
        if event.key() == Qt.Key_Backspace:
            self.navigate_to_parent()
        elif event.key() == Qt.Key_Delete:
            self.delete_selected_items()
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self.double_click_handler(self.table.currentIndex())
        elif event.key() == Qt.Key_F5:
            self.refresh_files()
        else:
            super().keyPressEvent(event)

    def refresh_files(self):
        """Refresh the file list."""
        self.get_files(force_refresh=True)
        self.message_signal.emit("Refreshed")

    def show_prompt_dialog(self, text, title):
        """Show a prompt dialog and return the user's response.
        
        Args:
            text: The prompt text
            title: The dialog title
            
        Returns:
            The user's response or None
        """
        text, ok = QInputDialog.getText(self, title, text)
        if ok:
            return text
        return None

    def on_header_clicked(self, logicalIndex):
        """Handle column header click for sorting.
        
        Args:
            logicalIndex: The index of the clicked column
        """
        if hasattr(self, 'proxy_model') and self.proxy_model:
            if self.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder:
                self.proxy_model.sort(logicalIndex, Qt.AscendingOrder)
            else:
                self.proxy_model.sort(logicalIndex, Qt.DescendingOrder)

    def toggle_tree_view(self):
        """Toggle the visibility of the tree view."""
        if hasattr(self, 'tree_view') and self.tree_view:
            visible = self.tree_view.isVisible()
            self.tree_view.setVisible(not visible)
            
            if hasattr(self, 'splitter') and self.splitter:
                if not visible:
                    self.splitter.setSizes([150, 400])
                else:
                    self.splitter.setSizes([0, 550])

    def populate_tree_view(self):
        """Populate the tree view with directory structure."""
        if not hasattr(self, 'tree_view') or not self.tree_view:
            return
            
        self.tree_view.clear()
        
        try:
            root_item = QTreeWidgetItem(["/"])
            self.tree_view.addTopLevelItem(root_item)
            
            self._populate_tree_item(root_item, "/")
        except Exception as e:
            self.message_signal.emit(f"Error populating tree: {e}")

    def _populate_tree_item(self, parent_item, path):
        """Populate a tree item with children.
        
        Args:
            parent_item: The parent tree item
            path: The path for this item
        """
        try:
            files = self.sftp_listdir(path)
            
            for filename in files:
                if not filename.startswith('.'):
                    full_path = path.rstrip('/') + '/' + filename
                    if self.is_remote_directory(full_path):
                        child_item = QTreeWidgetItem([filename])
                        parent_item.addChild(child_item)
                        child_item.setData(0, Qt.UserRole, full_path)
        except Exception as e:
            pass

    def tree_double_click_handler(self, item, column):
        """Handle double-click on tree item.
        
        Args:
            item: The clicked tree item
            column: The clicked column
        """
        path = item.data(0, Qt.UserRole)
        if path:
            self.change_directory(path)

    def tree_context_menu_handler(self, pos):
        """Show context menu for tree view.
        
        Args:
            pos: The position for the menu
        """
        item = self.tree_view.itemAt(pos)
        if not item:
            return
            
        menu = QMenu(self)
        menu.addAction("Navigate", lambda: self.tree_path_navigate(item.data(0, Qt.UserRole)))
        menu.addAction("Download", self.tree_download_selected)
        menu.addSeparator()
        menu.addAction("Expand All", lambda: self.tree_view.expandAll())
        menu.addAction("Collapse All", lambda: self.tree_view.collapseAll())
        
        menu.exec(self.tree_view.mapToGlobal(pos))

    def tree_item_expanded_handler(self, item):
        """Handle tree item expansion.
        
        Args:
            item: The expanded item
        """
        path = item.data(0, Qt.UserRole)
        if not path:
            return
            
        child_count = item.childCount()
        if child_count == 0:
            self._populate_tree_item(item, path)

    def tree_download_selected(self):
        """Download selected items from tree view."""
        item = self.tree_view.currentItem()
        if item:
            path = item.data(0, Qt.UserRole)
            if path:
                self.change_directory(path)
                self.upload_download()
