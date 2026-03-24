"""
PySide6 Compatibility Layer

Provides consistent enum access for Qt6/PySide6.
This layer exists for backward compatibility with code that uses our
custom Qt enum names.
"""
from PySide6 import QtCore
from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QCompleter, QTableWidget, QHeaderView, QTableView, QFrame, QSizePolicy, QMessageBox, QTextBrowser
from PySide6.QtCore import Qt

# Create backward-compatible Qt namespace
class QtCompat:
    # ItemDataRole
    DisplayRole = QtCore.Qt.ItemDataRole.DisplayRole
    UserRole = QtCore.Qt.ItemDataRole.UserRole
    FontRole = QtCore.Qt.ItemDataRole.FontRole
    ForegroundRole = QtCore.Qt.ItemDataRole.ForegroundRole
    
    # CheckState
    Unchecked = QtCore.Qt.CheckState.Unchecked
    PartiallyChecked = QtCore.Qt.CheckState.PartiallyChecked
    Checked = QtCore.Qt.CheckState.Checked
    
    # Orientation
    Horizontal = QtCore.Qt.Orientation.Horizontal
    Vertical = QtCore.Qt.Orientation.Vertical
    
    # SortOrder
    AscendingOrder = QtCore.Qt.SortOrder.AscendingOrder
    DescendingOrder = QtCore.Qt.SortOrder.DescendingOrder
    
    # AlignmentFlag
    AlignRight = QtCore.Qt.AlignmentFlag.AlignRight
    AlignCenter = QtCore.Qt.AlignmentFlag.AlignCenter
    
    # ScrollBarPolicy
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
    BlockingQueuedConnection = QtCore.Qt.ConnectionType.BlockingQueuedConnection
    AutoConnection = QtCore.Qt.ConnectionType.AutoConnection
    DirectConnection = QtCore.Qt.ConnectionType.DirectConnection
    
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
    
    # TextElideMode for QTableView
    TextElideMode_Left = Qt.TextElideMode.ElideLeft
    TextElideMode_Right = Qt.TextElideMode.ElideRight
    TextElideMode_Middle = Qt.TextElideMode.ElideMiddle
    TextElideMode_None = Qt.TextElideMode.ElideNone
    
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
    SizePolicy_Minimum = QSizePolicy.Policy.Minimum
    
    # LineWrapMode for QTextBrowser
    NoWrap = QTextBrowser.LineWrapMode.NoWrap
    
    # TextFormat for QMessageBox
    TextFormat_RichText = Qt.TextFormat.RichText
    TextFormat_PlainText = Qt.TextFormat.PlainText
    
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
    MsgRole_ActionRole = QMessageBox.ButtonRole.ActionRole
    
    # QMessageBox Icon
    MsgIcon_Question = QMessageBox.Icon.Question
    MsgIcon_Information = QMessageBox.Icon.Information
    MsgIcon_Warning = QMessageBox.Icon.Warning
    MsgIcon_Critical = QMessageBox.Icon.Critical
    
    # Event types
    User = QtCore.QEvent.Type.User
    KeyPress = QtCore.QEvent.Type.KeyPress
    
    # CursorShape
    PointingHandCursor = QtCore.Qt.CursorShape.PointingHandCursor
    ArrowCursor = QtCore.Qt.CursorShape.ArrowCursor
    
    # AspectRatioMode
    KeepAspectRatio = QtCore.Qt.AspectRatioMode.KeepAspectRatio
    
    # TransformationMode
    SmoothTransformation = QtCore.Qt.TransformationMode.SmoothTransformation
    
    # KeyboardModifier
    NoModifier = QtCore.Qt.KeyboardModifier.NoModifier
    
    # Additional Key codes
    Key_F2 = QtCore.Qt.Key.Key_F2
    Key_F6 = QtCore.Qt.Key.Key_F6
    Key_F7 = QtCore.Qt.Key.Key_F7
    Key_D = QtCore.Qt.Key.Key_D
    Key_L = QtCore.Qt.Key.Key_L
    Key_P = QtCore.Qt.Key.Key_P
    Key_R = QtCore.Qt.Key.Key_R
    Key_N = QtCore.Qt.Key.Key_N
    Key_W = QtCore.Qt.Key.Key_W
    Key_T = QtCore.Qt.Key.Key_T
    Key_Up = QtCore.Qt.Key.Key_Up
    Key_Down = QtCore.Qt.Key.Key_Down
    Key_Right = QtCore.Qt.Key.Key_Right
    Key_Left = QtCore.Qt.Key.Key_Left
    Key_Tab = QtCore.Qt.Key.Key_Tab
    
    # ItemSelectionModel flags
    Select = QtCore.QItemSelectionModel.SelectionFlag.Select
    Rows = QtCore.QItemSelectionModel.SelectionFlag.Rows
    
    # Mouse buttons
    LeftButton = QtCore.Qt.MouseButton.LeftButton
    RightButton = QtCore.Qt.MouseButton.RightButton
    MiddleButton = QtCore.Qt.MouseButton.MiddleButton

# Add QApplication for convenience
def get_qapplication():
    """Get QApplication instance safely"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

Qt = QtCompat