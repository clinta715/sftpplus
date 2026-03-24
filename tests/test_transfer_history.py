"""
Tests for Transfer History Module.

Tests the logging, retrieval, and export of transfer history.
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest


class TestTransferHistoryLogging:
    """Tests for logging transfer operations"""
    
    def setup_method(self):
        """Set up test environment"""
        from sftp_transfer_history import HISTORY_FILE, _history_lock
        # Use temp directory for tests
        self.temp_dir = tempfile.mkdtemp()
        self.test_history_file = os.path.join(self.temp_dir, 'history.json')
        
    def teardown_method(self):
        """Clean up test environment"""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_log_successful_download(self):
        """Test logging a successful download"""
        from sftp_transfer_history import log_transfer, get_history, clear_history, HISTORY_FILE
        
        # Override history file location for test
        import sftp_transfer_history
        original_file = sftp_transfer_history.HISTORY_FILE
        sftp_transfer_history.HISTORY_FILE = self.test_history_file
        
        try:
            clear_history()
            
            entry = log_transfer(
                source_path='/remote/file.txt',
                destination_path='/local/file.txt',
                direction='download',
                hostname='test.example.com',
                username='testuser',
                file_size=1024,
                status='success'
            )
            
            assert entry['source_path'] == '/remote/file.txt'
            assert entry['direction'] == 'download'
            assert entry['status'] == 'success'
            assert entry['file_size'] == 1024
            assert 'timestamp' in entry
            
            # Verify it was saved
            history = get_history()
            assert len(history) == 1
            assert history[0]['source_path'] == '/remote/file.txt'
        finally:
            sftp_transfer_history.HISTORY_FILE = original_file
    
    def test_log_failed_upload(self):
        """Test logging a failed upload"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        
        import sftp_transfer_history
        original_file = sftp_transfer_history.HISTORY_FILE
        sftp_transfer_history.HISTORY_FILE = self.test_history_file
        
        try:
            clear_history()
            
            entry = log_transfer(
                source_path='/local/file.txt',
                destination_path='/remote/file.txt',
                direction='upload',
                hostname='test.example.com',
                username='testuser',
                file_size=2048,
                status='failed',
                error_message='Connection refused'
            )
            
            assert entry['status'] == 'failed'
            assert entry['direction'] == 'upload'
            assert entry['error_message'] == 'Connection refused'
            
            history = get_history()
            assert len(history) == 1
            assert history[0]['status'] == 'failed'
        finally:
            sftp_transfer_history.HISTORY_FILE = original_file
    
    def test_log_multiple_transfers(self):
        """Test logging multiple transfers"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        
        import sftp_transfer_history
        original_file = sftp_transfer_history.HISTORY_FILE
        sftp_transfer_history.HISTORY_FILE = self.test_history_file
        
        try:
            clear_history()
            
            log_transfer('/remote/a.txt', '/local/a.txt', 'download', status='success')
            log_transfer('/local/b.txt', '/remote/b.txt', 'upload', status='success')
            log_transfer('/remote/c.txt', '/local/c.txt', 'download', status='failed', error_message='Timeout')
            
            history = get_history()
            assert len(history) == 3
            
            # Verify order (newest first)
            assert history[0]['status'] == 'failed'
            assert history[1]['direction'] == 'upload'
            assert history[2]['direction'] == 'download'
        finally:
            sftp_transfer_history.HISTORY_FILE = original_file


class TestTransferHistoryRetrieval:
    """Tests for retrieving transfer history"""
    
    def setup_method(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_history_file = os.path.join(self.temp_dir, 'history.json')
        import sftp_transfer_history
        sftp_transfer_history.HISTORY_FILE = self.test_history_file
        
    def teardown_method(self):
        """Clean up test environment"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_get_history_with_limit(self):
        """Test getting history with limit"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        
        clear_history()
        
        for i in range(10):
            log_transfer(f'/remote/{i}.txt', f'/local/{i}.txt', 'download', status='success')
        
        history = get_history(limit=5)
        assert len(history) == 5
    
    def test_get_history_filter_by_direction(self):
        """Test filtering history by direction"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        
        clear_history()
        
        log_transfer('/remote/1.txt', '/local/1.txt', 'download', status='success')
        log_transfer('/local/2.txt', '/remote/2.txt', 'upload', status='success')
        log_transfer('/remote/3.txt', '/local/3.txt', 'download', status='success')
        
        downloads = get_history(direction='download')
        uploads = get_history(direction='upload')
        
        assert len(downloads) == 2
        assert len(uploads) == 1
    
    def test_get_history_filter_by_status(self):
        """Test filtering history by status"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        
        clear_history()
        
        log_transfer('/1.txt', '/1.txt', 'download', status='success')
        log_transfer('/2.txt', '/2.txt', 'download', status='failed')
        log_transfer('/3.txt', '/3.txt', 'download', status='success')
        
        successes = get_history(status='success')
        failures = get_history(status='failed')
        
        assert len(successes) == 2
        assert len(failures) == 1
    
    def test_get_history_filter_by_hostname(self):
        """Test filtering history by hostname"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        
        clear_history()
        
        log_transfer('/1.txt', '/1.txt', 'download', hostname='server1.com', status='success')
        log_transfer('/2.txt', '/2.txt', 'download', hostname='server2.com', status='success')
        log_transfer('/3.txt', '/3.txt', 'download', hostname='server1.com', status='success')
        
        history = get_history(hostname='server1.com')
        
        assert len(history) == 2


class TestTransferHistoryStatistics:
    """Tests for transfer statistics"""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        import sftp_transfer_history
        sftp_transfer_history.HISTORY_FILE = os.path.join(self.temp_dir, 'history.json')
    
    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_empty_statistics(self):
        """Test statistics with no history"""
        from sftp_transfer_history import get_statistics, clear_history
        
        clear_history()
        stats = get_statistics()
        
        assert stats['total_transfers'] == 0
        assert stats['uploads'] == 0
        assert stats['downloads'] == 0
        assert stats['success_count'] == 0
        assert stats['failed_count'] == 0
        assert stats['total_bytes'] == 0
        assert stats['success_rate'] == 0.0
    
    def test_statistics_with_transfers(self):
        """Test statistics with transfer history"""
        from sftp_transfer_history import log_transfer, get_statistics, clear_history
        
        clear_history()
        
        log_transfer('/1.txt', '/1.txt', 'download', file_size=100, status='success')
        log_transfer('/2.txt', '/2.txt', 'upload', file_size=200, status='success')
        log_transfer('/3.txt', '/3.txt', 'download', file_size=300, status='failed')
        
        stats = get_statistics()
        
        assert stats['total_transfers'] == 3
        assert stats['uploads'] == 1
        assert stats['downloads'] == 2
        assert stats['success_count'] == 2
        assert stats['failed_count'] == 1
        assert stats['total_bytes'] == 600
        assert stats['success_rate'] == pytest.approx(2/3, rel=0.01)


class TestTransferHistoryExport:
    """Tests for exporting transfer history"""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        import sftp_transfer_history
        sftp_transfer_history.HISTORY_FILE = os.path.join(self.temp_dir, 'history.json')
    
    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_export_to_json(self):
        """Test exporting history to JSON"""
        from sftp_transfer_history import log_transfer, export_history, clear_history
        
        clear_history()
        
        log_transfer('/1.txt', '/1.txt', 'download', status='success')
        log_transfer('/2.txt', '/2.txt', 'upload', status='success')
        
        output_path = os.path.join(self.temp_dir, 'export.json')
        count = export_history(output_path, format='json')
        
        assert count == 2
        assert os.path.exists(output_path)
        
        with open(output_path) as f:
            data = json.load(f)
        assert len(data) == 2
    
    def test_export_to_csv(self):
        """Test exporting history to CSV"""
        from sftp_transfer_history import log_transfer, export_history, clear_history
        
        clear_history()
        
        log_transfer('/1.txt', '/1.txt', 'download', status='success', file_size=100)
        
        output_path = os.path.join(self.temp_dir, 'export.csv')
        count = export_history(output_path, format='csv')
        
        assert count == 1
        assert os.path.exists(output_path)
        
        with open(output_path) as f:
            content = f.read()
        assert 'timestamp' in content
        assert 'download' in content
        assert '/1.txt' in content
    
    def test_export_to_txt(self):
        """Test exporting history to text"""
        from sftp_transfer_history import log_transfer, export_history, clear_history
        
        clear_history()
        
        log_transfer('/remote/file.txt', '/local/file.txt', 'download', 
                     hostname='test.com', file_size=1024, status='success')
        
        output_path = os.path.join(self.temp_dir, 'export.txt')
        count = export_history(output_path, format='txt')
        
        assert count == 1
        assert os.path.exists(output_path)
        
        with open(output_path) as f:
            content = f.read()
        assert 'download' in content
        assert '/remote/file.txt' in content
        assert '/local/file.txt' in content
        assert 'success' in content


class TestTransferHistoryThreadSafety:
    """Tests for thread safety"""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        import sftp_transfer_history
        sftp_transfer_history.HISTORY_FILE = os.path.join(self.temp_dir, 'history.json')
    
    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_concurrent_logging(self):
        """Test concurrent log_transfer calls"""
        from sftp_transfer_history import log_transfer, get_history, clear_history
        import threading
        
        clear_history()
        errors = []
        
        def log_entry(i):
            try:
                log_transfer(f'/file{i}.txt', f'/local{i}.txt', 'download', status='success')
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=log_entry, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        
        history = get_history()
        assert len(history) == 20


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])