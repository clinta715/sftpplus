
import pytest
from unittest.mock import MagicMock, patch
from sftp_transfer_queue_widget import TransferQueueWidget

@pytest.fixture
def transfer_widget(qtbot):
    # Mock QTimer and other dependencies that might trigger background threads
    with patch('sftp_transfer_queue_widget.QTimer'):
        widget = TransferQueueWidget()
        qtbot.addWidget(widget)
        return widget

def test_overall_progress_aggregation(transfer_widget):
    # Setup multiple transfers
    transfer_widget._transfer_displays = {
        't1': {'status': 'complete', 'bytes_total': 1000, 'bytes_done': 1000},
        't2': {'status': 'transferring', 'bytes_total': 1000, 'bytes_done': 500, 'is_active': True, 'speed_bps': 100},
        't3': {'status': 'queued', 'bytes_total': 1000, 'bytes_done': 0}
    }
    
    transfer_widget.update_overall_progress()
    
    # Total bytes: 3000, Completed bytes: 1500 (1000 from t1, 500 from t2)
    # 3000 / 1024 = 2.929 KB, 1500 / 1024 = 1.464 KB
    # Expected progress: 50%
    assert transfer_widget.overall_progress_bar.value() == 50
    assert "1.5 KB/2.9 KB" in transfer_widget.overall_progress_label.text()
    assert "50%" in transfer_widget.overall_progress_label.text()

def test_overall_progress_no_jump_backwards(transfer_widget):
    # Start with one active transfer at 100%
    transfer_widget._transfer_displays = {
        't1': {'status': 'transferring', 'bytes_total': 1000, 'bytes_done': 1000, 'is_active': True, 'speed_bps': 0}
    }
    transfer_widget.update_overall_progress()
    assert transfer_widget.overall_progress_bar.value() == 100
    
    # Mark it complete - should stay at 100%
    transfer_widget._transfer_displays['t1']['status'] = 'complete'
    transfer_widget._transfer_displays['t1']['is_active'] = False
    transfer_widget.update_overall_progress()
    assert transfer_widget.overall_progress_bar.value() == 100
    
    # Add a second transfer at 0% - should drop to 50%, NOT 0%
    transfer_widget._transfer_displays['t2'] = {'status': 'queued', 'bytes_total': 1000, 'bytes_done': 0}
    transfer_widget.update_overall_progress()
    assert transfer_widget.overall_progress_bar.value() == 50

def test_overall_progress_files_fallback(transfer_widget):
    # Case where byte sizes are 0 (e.g. empty files)
    transfer_widget._transfer_displays = {
        't1': {'status': 'complete', 'bytes_total': 0, 'bytes_done': 0},
        't2': {'status': 'queued', 'bytes_total': 0, 'bytes_done': 0}
    }
    transfer_widget.update_overall_progress()
    
    # Total files: 2, Completed files: 1
    # Expected progress: 50%
    assert transfer_widget.overall_progress_bar.value() == 50
    assert "1/2 files" in transfer_widget.overall_progress_label.text()
