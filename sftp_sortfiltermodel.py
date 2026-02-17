from PyQt5.QtCore import QSortFilterProxyModel, Qt, QModelIndex
import stat
import os


class DirectoryFirstSortProxyModel(QSortFilterProxyModel):
    def lessThan(self, left, right):
        left_data = self.sourceModel().data(left, Qt.DisplayRole)
        right_data = self.sourceModel().data(right, Qt.DisplayRole)

        if not left_data or not right_data:
            return super().lessThan(left, right)

        left_text = left_data if isinstance(left_data, str) else str(left_data)
        right_text = right_data if isinstance(right_data, str) else str(right_data)

        source_model = self.sourceModel()
        left_is_dir = False
        right_is_dir = False

        if hasattr(source_model, 'file_list') and source_model.file_list:
            if 0 <= left.row() < len(source_model.file_list):
                left_file = source_model.file_list[left.row()]
                if hasattr(source_model, 'is_remote_browser') and source_model.is_remote_browser():
                    left_is_dir = stat.S_ISDIR(left_file[2]) if len(left_file) > 2 else False
                else:
                    name = left_file[0] if isinstance(left_file, list) else str(left_file)
                    if name == "..":
                        left_is_dir = True
                    elif hasattr(source_model, 'directory'):
                        full_path = os.path.join(str(source_model.directory), name)
                        left_is_dir = os.path.isdir(full_path)

            if 0 <= right.row() < len(source_model.file_list):
                right_file = source_model.file_list[right.row()]
                if hasattr(source_model, 'is_remote_browser') and source_model.is_remote_browser():
                    right_is_dir = stat.S_ISDIR(right_file[2]) if len(right_file) > 2 else False
                else:
                    name = right_file[0] if isinstance(right_file, list) else str(right_file)
                    if name == "..":
                        right_is_dir = True
                    elif hasattr(source_model, 'directory'):
                        full_path = os.path.join(str(source_model.directory), name)
                        right_is_dir = os.path.isdir(full_path)

        left_is_dir = left_is_dir or left_text.startswith('[DIR]') or left_text.startswith('📁')
        right_is_dir = right_is_dir or right_text.startswith('[DIR]') or right_text.startswith('📁')

        if left_is_dir and not right_is_dir:
            return True
        if not left_is_dir and right_is_dir:
            return False

        left_clean = left_text.lstrip('[DIR] ').lstrip('📁 ').lstrip('📄 ')
        right_clean = right_text.lstrip('[DIR] ').lstrip('📁 ').lstrip('📄 ')

        ascending = self.sortOrder() == Qt.AscendingOrder
        if ascending:
            return left_clean.lower() < right_clean.lower()
        else:
            return left_clean.lower() > right_clean.lower()
