from PySide6.QtCore import QSortFilterProxyModel, QModelIndex
from sftp_qt_compat import Qt  # Use compatibility layer for Qt enums
import stat
import os


class DirectoryFirstSortProxyModel(QSortFilterProxyModel):
    """
    Proxy model that ensures directories always appear at the top of the list,
    followed by files, with both groups sorted according to the current sort column.
    """
    
    def lessThan(self, left, right):
        # Get data from source model
        left_data = self.sourceModel().data(left, Qt.DisplayRole)
        right_data = self.sourceModel().data(right, Qt.DisplayRole)

        if left_data is None or right_data is None:
            return super().lessThan(left, right)

        left_text = str(left_data)
        right_text = str(right_data)

        # 1. Handle ".." (parent directory) - always first
        if left_text == "..":
            return self.sortOrder() == Qt.AscendingOrder
        if right_text == "..":
            return self.sortOrder() != Qt.AscendingOrder

        # 2. Identify if items are directories
        # Remote model uses [DIR] prefix, local model uses 📁 prefix
        left_is_dir = left_text.startswith('[DIR]') or left_text.startswith('📁')
        right_is_dir = right_text.startswith('[DIR]') or right_text.startswith('📁')

        # 3. Directory vs File logic
        if left_is_dir and not right_is_dir:
            return self.sortOrder() == Qt.AscendingOrder
        if not left_is_dir and right_is_dir:
            return self.sortOrder() != Qt.AscendingOrder

        # 4. Both are same type (both dirs or both files) - sort by the active column
        sort_column = self.sortColumn()
        
        # Get raw data for comparison if it's not the name column
        if sort_column != 0:
            left_val = self.sourceModel().data(left.sibling(left.row(), sort_column), Qt.DisplayRole)
            right_val = self.sourceModel().data(right.sibling(right.row(), sort_column), Qt.DisplayRole)
            
            if left_val is not None and right_val is not None:
                # Size column - numeric sort
                if sort_column == 1:
                    try:
                        return int(left_val) < int(right_val)
                    except (ValueError, TypeError):
                        pass
                
                # Other columns - string sort
                return str(left_val).lower() < str(right_val).lower()

        # Name column (or fallback) - remove prefixes and compare
        left_clean = left_text
        right_clean = right_text
        
        prefixes = ['[DIR]', '[FILE]', '[LINK]', '📁', '📄', '🔗']
        for prefix in prefixes:
            if left_clean.startswith(prefix):
                left_clean = left_clean[len(prefix):].lstrip()
            if right_clean.startswith(prefix):
                right_clean = right_clean[len(prefix):].lstrip()

        return left_clean.lower() < right_clean.lower()
