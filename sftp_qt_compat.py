"""
PyQt6 Compatibility Layer

Provides backward-compatible enum access for code written for PyQt5.
"""
from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication, QLineEdit, QComboBox, QCompleter, QTableWidget, QHeaderView, QTableView, QFrame, QSizePolicy, QMessageBox
from PyQt6.QtCore import Qt

# Create backward-compatible Qt namespace
class QtCompat:
    # ItemDataRole
    DisplayRole = QtCore.Qt.ItemDataRole.DisplayRole
    UserRole = QtCore.Qt.ItemDataRole.UserRole
    FontRole = QtCore.Qt.ItemDataRole.FontRole
    ForegroundRole = QtCore.Qt.ItemDataRole.ForegroundRole
    
    # Orientation
    Horizontal = QtCore.Qt.Orientation.Horizontal
    Vertical = QtCore.Qt.Orientation.Vertical
    
    # SortOrder
    AscendingOrder = QtCore.Qt.SortOrder.AscendingOrder
    DescendingOrder = QtCore.Qt.SortOrder.DescendingOrder
    
    # AlignmentFlag
    AlignRight = QtCore.Qt.AlignmentFlag.AlignRight
    AlignCenter = QtCore.Qt.AlignmentFlag.AlignCenter
    
    # ScrollBarPolicy - use Qt.ScrollBarPolicy enum for compatibility
    ScrollBarAsNeeded = Qt.ScrollBarPolicy.ScrollBarAsNeeded
    ScrollBarAlwaysOn = Qt.ScrollBarPolicy.ScrollBarAlwaysOn
    
    # FocusPolicy
    StrongFocus = QtCore.Qt.FocusPolicy.StrongFocus
    
    # ContextMenuPolicy
    CustomContextMenu = QtCore.Qt.ContextMenuPolicy.CustomContextMenu
    
    # CaseSensitivity
    CaseInsensitive = QtCore.Qt.CaseSensitivity.CaseInsensitive
    CaseSensitive = QtCore.Qt.CaseSensitivity.CaseSensitive
    
    # Key
    Key_Backspace = QtCore.Qt.Key.Key_Backspace
    Key_Delete = QtCore.Qt.Key.Key_Delete
    Key_Return = QtCore.Qt.Key.Key_Return
    Key_Enter = QtCore.Qt.Key.Key_Enter
    Key_F5 = QtCore.Qt.Key.Key_F5
    Key_A = QtCore.Qt.Key.Key_A
    Key_B = QtCore.Qt.Key.Key_B
    
    # KeyboardModifier
    ControlModifier = QtCore.Qt.KeyboardModifier.ControlModifier
    
    # ConnectionType
    QueuedConnection = QtCore.Qt.ConnectionType.QueuedConnection
    
    # ISODate format
    ISODate = QtCore.Qt.DateFormat.ISODate
    
    # EchoMode for QLineEdit
    Password = QLineEdit.EchoMode.Password
    
    # SizeAdjustPolicy for QComboBox
    ComboBox_AdjustToContents = QComboBox.SizeAdjustPolicy.AdjustToContents
    
    # CompletionMode for QCompleter
    Completer_PopupCompletion = QCompleter.CompletionMode.PopupCompletion
    
    # SelectionBehavior for QTableWidget
    TableWidget_SelectRows = QTableWidget.SelectionBehavior.SelectRows
    
    # ResizeMode for QHeaderView
    HeaderView_Stretch = QHeaderView.ResizeMode.Stretch
    HeaderView_ResizeToContents = QHeaderView.ResizeMode.ResizeToContents
    HeaderView_Interactive = QHeaderView.ResizeMode.Interactive
    
    # SelectionBehavior and SelectionMode for QTableView
    TableView_SelectRows = QTableView.SelectionBehavior.SelectRows
    TableView_ExtendedSelection = QTableView.SelectionMode.ExtendedSelection
    
    # SelectionMode for QTableWidget
    TableWidget_SingleSelection = QTableWidget.SelectionMode.SingleSelection
    
    # FrameShape for QFrame
    Frame_HLine = QFrame.Shape.HLine
    Frame_VLine = QFrame.Shape.VLine
    Frame_NoFrame = QFrame.Shape.NoFrame
    Frame_Sunken = QFrame.Shadow.Sunken
    
    # Policy for QSizePolicy
    SizePolicy_Expanding = QSizePolicy.Policy.Expanding
    SizePolicy_Fixed = QSizePolicy.Policy.Fixed
    
    # GlobalColor for QColor
    Color_blue = QtCore.Qt.GlobalColor.blue
    Color_darkGray = QtCore.Qt.GlobalColor.darkGray
    
    # QMessageBox StandardButton
    MsgBtn_Yes = QMessageBox.StandardButton.Yes
    MsgBtn_No = QMessageBox.StandardButton.No
    MsgBtn_Ok = QMessageBox.StandardButton.Ok
    MsgBtn_Cancel = QMessageBox.StandardButton.Cancel
    MsgBtn_YesToAll = QMessageBox.StandardButton.YesToAll
    MsgBtn_NoToAll = QMessageBox.StandardButton.NoToAll
    MsgBtn_Abort = QMessageBox.StandardButton.Abort
    MsgBtn_Retry = QMessageBox.StandardButton.Retry
    MsgBtn_Ignore = QMessageBox.StandardButton.Ignore
    
    # QMessageBox ButtonRole
    MsgRole_YesRole = QMessageBox.ButtonRole.YesRole
    MsgRole_NoRole = QMessageBox.ButtonRole.NoRole
    MsgRole_AcceptRole = QMessageBox.ButtonRole.AcceptRole
    MsgRole_RejectRole = QMessageBox.ButtonRole.RejectRole
    
    # Event types
    User = QtCore.QEvent.Type.User
    KeyPress = QtCore.QEvent.Type.KeyPress

# Add QApplication for convenience
def get_qapplication():
    """Get QApplication instance safely"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

Qt = QtCompat
