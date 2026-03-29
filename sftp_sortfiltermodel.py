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

        # 2. Identify if items are directories (bold font = directory)
        left_font = self.sourceModel().data(left, Qt.FontRole)
        right_font = self.sourceModel().data(right, Qt.FontRole)
        left_is_dir = left_font is not None and left_font.bold()
        right_is_dir = right_font is not None and right_font.bold()

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

        # Name column (or fallback) - compare directly
        return left_text.lower() < right_text.lower()
