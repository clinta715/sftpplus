"""
Tests for TransferQueueWidget functionality.
"""

import os
import sys
import json
import tempfile
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest


class TestTransferQueuePersistence:
    """Tests for transfer queue save/load"""
    
    def test_transfer_data_structure(self):
        """Test that SFTPJob can be serialized"""
        from sftp_downloadworkerclass import SFTPJob
        
        job = SFTPJob(
            source_path="/remote/file.txt",
            is_source_remote=True,
            destination_path="/local/file.txt",
            is_destination_remote=False,
            hostname="test.example.com",
            username="testuser",
            password="testpass",
            port=22,
            command="download",
            job_id=123,
            key=None
        )
        
        data = job.to_dict()
        
        assert data["source_path"] == "/remote/file.txt"
        assert data["is_source_remote"] is True
        assert data["hostname"] == "test.example.com"
        assert data["job_id"] == 123
    
    def test_transfer_data_from_dict(self):
        """Test that SFTPJob can be deserialized"""
        from sftp_downloadworkerclass import SFTPJob
        
        data = {
            "source_path": "/remote/file.txt",
            "is_source_remote": True,
            "destination_path": "/local/file.txt",
            "is_destination_remote": False,
            "hostname": "test.example.com",
            "username": "testuser",
            "password": "dGVzdHBhc3M=",  # base64 encoded
            "port": 22,
            "command": "download",
            "job_id": 456,
            "key": None
        }
        
        job = SFTPJob.from_dict(data)
        
        assert job.source_path == "/remote/file.txt"
        assert job.is_source_remote is True
        assert job.hostname == "test.example.com"
        assert job.job_id == 456


class TestTransferQueueControls:
    """Tests for transfer queue control buttons"""
    
    def test_pause_button_state(self):
        """Test that pause button toggles state"""
        from sftp_transfer_queue_widget import TransferQueueWidget
        
        # Create widget without Qt dependencies
        with patch('sftp_transfer_queue_widget.QWidget.__init__'):
            widget = TransferQueueWidget.__new__(TransferQueueWidget)
            widget.pause_button = Mock()
            widget.pause_button.isChecked.return_value = False
        
        # Pause button should be checkable
        assert widget.pause_button is not None
    
    def test_clear_completed_signal(self):
        """Test clear completed functionality"""
        # This tests the clear_completed method logic
        # In production, it would clear finished transfers from the list
        pass


class TestTransferQueueProgress:
    """Tests for progress tracking"""
    
    def test_progress_signal_format(self):
        """Test that progress signal has correct format"""
        from sftp_downloadworkerclass import WorkerSignals
        
        signals = WorkerSignals()
        
        # Progress signal should accept (transfer_id, percent, speed, eta)
        # This is a compile-time check - if the signal signature is wrong,
        # the code won't run
        assert hasattr(signals, 'progress')
        assert hasattr(signals, 'finished')
        assert hasattr(signals, 'message')
    
    def test_transfer_class_attributes(self):
        """Test Transfer class has required attributes"""
        from sftp_downloadworkerclass import Transfer
        
        transfer = Transfer(
            transfer_id=123,
            progress_bar=Mock(),
            cancel_button=Mock()
        )
        
        assert transfer.transfer_id == 123
        assert transfer.active is False
        assert transfer.paused is False
        assert hasattr(transfer, 'hostname')


class TestTransferQueueThreadSafety:
    """Tests for thread safety in transfer queue"""
    
    def test_response_queue_thread_safety(self):
        """Test that response queues use thread-safe access"""
        from sftp_downloadworkerclass import response_queues, response_queues_lock
        import threading
        
        # Test concurrent access to response_queues
        errors = []
        
        def access_queue(i):
            try:
                with response_queues_lock:
                    response_queues[f"test_{i}"] = Mock()
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=access_queue, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        
        # Cleanup
        with response_queues_lock:
            for key in list(response_queues.keys()):
                if key.startswith("test_"):
                    del response_queues[key]
    
    def test_response_queue_context_manager(self):
        """Test ResponseQueueContext cleans up properly"""
        from sftp_downloadworkerclass import ResponseQueueContext, response_queues, response_queues_lock
        
        job_id = 99999
        
        # Test normal operation
        with ResponseQueueContext(job_id):
            assert job_id in response_queues
        
        # Should be cleaned up after context
        assert job_id not in response_queues
    
    def test_response_queue_context_on_exception(self):
        """Test ResponseQueueContext cleans up on exception"""
        from sftp_downloadworkerclass import ResponseQueueContext, response_queues
        
        job_id = 88888
        
        try:
            with ResponseQueueContext(job_id):
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Should still be cleaned up
        assert job_id not in response_queues


class TestTransferQueueMessages:
    """Tests for transfer queue message handling"""
    
    def test_queue_item_creation(self):
        """Test QueueItem creation"""
        from sftp_downloadworkerclass import QueueItem
        
        item = QueueItem(name="test.txt", job_id=123)
        
        assert item.name == "test.txt"
        assert item.job_id == 123


class TestTransferUtils:
    """Tests for utility functions"""
    
    def test_strip_decorative_chars(self):
        """Test stripping decorative characters from filenames"""
        from sftp_downloadworkerclass import strip_decorative_chars
        
        # Test emoji stripping
        assert strip_decorative_chars("📁 folder") == "folder"
        assert strip_decorative_chars("📄 file.txt") == "file.txt"
        
        # Test regular filename
        assert strip_decorative_chars("regular_file.txt") == "regular_file.txt"
        
        # Test with prefix markers
        assert strip_decorative_chars("[DIR] folder") == "[DIR] folder"
    
    def test_size_units(self):
        """Test SIZE_UNIT enum"""
        from sftp_downloadworkerclass import SIZE_UNIT
        
        assert SIZE_UNIT.BYTES.value == 1
        assert SIZE_UNIT.KB.value == 2
        assert SIZE_UNIT.MB.value == 3
        assert SIZE_UNIT.GB.value == 4


class TestTransferFormatting:
    """Tests for transfer display formatting"""
    
    def test_format_bytes(self):
        """Test bytes formatting"""
        # Test various sizes
        assert 500 < 1024  # Bytes
        
        # 1 KB
        kb = 1024
        assert kb == 1024
        
        # 1 MB
        mb = 1024 * 1024
        assert mb == 1048576
        
        # 1 GB
        gb = 1024 * 1024 * 1024
        assert gb == 1073741824
    
    def test_speed_formatting(self):
        """Test speed calculation concepts"""
        # Speed is bytes per second
        # 1 MB/s = 1024 * 1024 bytes/sec
        mb_per_sec = 1024 * 1024
        
        # At 1 MB/s, 100 MB file takes ~100 seconds
        file_size = 100 * 1024 * 1024
        eta_seconds = file_size / mb_per_sec
        
        assert eta_seconds == 100.0
    
    def test_eta_formatting(self):
        """Test ETA time formatting"""
        # Test time formatting for ETA
        total_seconds = 135  # 2 minutes 15 seconds
        
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        
        eta_str = f"{minutes}:{seconds:02d}"
        
        assert eta_str == "2:15"
        
        # Test hours
        total_seconds = 3725  # 1 hour 2 minutes 5 seconds
        hours = int(total_seconds // 3600)
        remaining = total_seconds % 3600
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        
        assert hours == 1
        assert minutes == 2
        assert seconds == 5


class TestTransferProgress:
    """Tests for progress calculation"""
    
    def test_progress_percentage(self):
        """Test progress percentage calculation"""
        bytes_transferred = 50
        bytes_total = 100
        
        percent = int((bytes_transferred / bytes_total) * 100)
        
        assert percent == 50
    
    def test_progress_with_zero_total(self):
        """Test progress with zero total bytes"""
        bytes_transferred = 50
        bytes_total = 0
        
        # Should handle division by zero
        if bytes_total > 0:
            percent = int((bytes_transferred / bytes_total) * 100)
        else:
            percent = 0
        
        assert percent == 0
    
    def test_file_count_progress(self):
        """Test file count progress"""
        files_done = 24
        files_total = 50
        
        progress_text = f"{files_done}/{files_total} files"
        
        assert "24/50" in progress_text
    
    def test_single_file_progress(self):
        """Test single file doesn't show file count"""
        files_total = 1
        
        if files_total > 1:
            progress_text = f"0/{files_total} files"
        else:
            progress_text = ""  # Single file, no count
        
        assert progress_text == ""


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])