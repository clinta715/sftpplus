"""
Tests for sftp_hostdataeditor module.

Run with: python -m pytest tests/test_hostdataeditor.py -v
"""
import os
import sys
import tempfile
import shutil

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHostDataEditorAPI:
    """Test the host data editor API functions."""

    @pytest.fixture(autouse=True)
    def setup_test_env(self, tmp_path, monkeypatch):
        """Set up test environment with temp directories."""
        from sftp_platform import get_key_file_path, get_connection_data_path

        test_key_dir = tmp_path / "sftp_test_keys"
        test_data_dir = tmp_path / "sftp_test_data"
        test_key_dir.mkdir(parents=True, exist_ok=True)
        test_data_dir.mkdir(parents=True, exist_ok=True)

        def mock_key_path():
            return str(test_key_dir / "test_key")

        def mock_data_path():
            return str(test_data_dir / "test_connection_data.json")

        monkeypatch.setattr("sftp_platform.get_key_file_path", mock_key_path)
        monkeypatch.setattr("sftp_platform.get_connection_data_path", mock_data_path)

        self._cleanup_func = lambda: None
        yield
        self._cleanup_func()

    def test_save_and_load_returns_dict(self):
        """Test that save_connection_data and load_connection_data work."""
        from sftp_hostdataeditor import save_connection_data, load_connection_data

        data = load_connection_data()
        assert isinstance(data, dict)
        assert "hostnames" in data

        result = save_connection_data(data)
        assert isinstance(result, bool)

    def test_update_connection_data_atomic(self):
        """Test that update_connection_data atomically loads, modifies, and saves."""
        from sftp_hostdataeditor import update_connection_data, load_connection_data

        def callback(host_data):
            host_data["hostnames"]["test_atomic"] = "test_atomic"
            host_data["usernames"]["test_atomic"] = "testuser"
            host_data["passwords"]["test_atomic"] = "testpass"
            host_data["ports"]["test_atomic"] = 22
            host_data["key"]["test_atomic"] = ""

        result = update_connection_data(callback)
        assert result is True

        data = load_connection_data()
        assert "test_atomic" in data["hostnames"]
        assert data["usernames"]["test_atomic"] == "testuser"

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict):
                    host_data[key].pop("test_atomic", None)
        update_connection_data(cleanup)

    def test_get_site_names_returns_list(self):
        """Test that get_site_names returns a list."""
        from sftp_hostdataeditor import get_site_names, update_connection_data

        def add_test_site(host_data):
            host_data["hostnames"]["test_names"] = "test_names"

        update_connection_data(add_test_site)

        names = get_site_names()
        assert isinstance(names, list)
        assert "test_names" in names

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict):
                    host_data[key].pop("test_names", None)
        update_connection_data(cleanup)

    def test_get_site_data_returns_dict_or_none(self):
        """Test that get_site_data returns dict or None."""
        from sftp_hostdataeditor import get_site_data, update_connection_data

        def add_site(host_data):
            host_data["hostnames"]["test_site_data"] = "test_site_data"
            host_data["usernames"]["test_site_data"] = "myuser"
            host_data["passwords"]["test_site_data"] = "mypass"
            host_data["ports"]["test_site_data"] = 2222

        update_connection_data(add_site)

        site = get_site_data("test_site_data")
        assert site is not None
        assert isinstance(site, dict)
        assert site["username"] == "myuser"
        assert site["port"] == 2222

        missing = get_site_data("nonexistent_host")
        assert missing is None

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict):
                    host_data[key].pop("test_site_data", None)
        update_connection_data(cleanup)

    def test_get_setting_with_default(self):
        """Test get_setting returns default for nonexistent keys."""
        from sftp_hostdataeditor import get_setting

        val = get_setting("nonexistent_key_xyz", "default_value")
        assert val == "default_value"

        val2 = get_setting("show_manager_on_startup", True)
        assert isinstance(val2, bool)

    def test_delete_site_function(self):
        """Test that delete_site removes a site."""
        from sftp_hostdataeditor import delete_site, get_site_data, update_connection_data

        def add_site(host_data):
            host_data["hostnames"]["site_to_delete"] = "site_to_delete"
            host_data["usernames"]["site_to_delete"] = "user"
        update_connection_data(add_site)

        assert get_site_data("site_to_delete") is not None

        result = delete_site("site_to_delete")
        assert result is True
        assert get_site_data("site_to_delete") is None

    def test_copy_site_function(self):
        """Test that copy_site duplicates a site."""
        from sftp_hostdataeditor import copy_site, get_site_data, update_connection_data

        def add_source(host_data):
            host_data["hostnames"]["copy_source"] = "copy_source"
            host_data["usernames"]["copy_source"] = "original_user"
            host_data["ports"]["copy_source"] = 1234
        update_connection_data(add_source)

        result = copy_site("copy_source", "copy_destination")
        assert result is True

        source = get_site_data("copy_source")
        dest = get_site_data("copy_destination")
        assert dest is not None
        assert dest["username"] == source["username"]
        assert dest["port"] == source["port"]

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict):
                    host_data[key].pop("copy_source", None)
                    host_data[key].pop("copy_destination", None)
        update_connection_data(cleanup)

    def test_rename_site_function(self):
        """Test that rename_site changes hostname."""
        from sftp_hostdataeditor import rename_site, get_site_data, update_connection_data

        def add_site(host_data):
            host_data["hostnames"]["old_name"] = "old_name"
            host_data["usernames"]["old_name"] = "user"
        update_connection_data(add_site)

        result = rename_site("old_name", "new_name")
        assert result is True

        assert get_site_data("old_name") is None
        renamed = get_site_data("new_name")
        assert renamed is not None
        assert renamed["username"] == "user"

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict):
                    host_data[key].pop("new_name", None)
        update_connection_data(cleanup)

    def test_ports_normalized_to_int(self):
        """Test that ports are loaded as integers."""
        from sftp_hostdataeditor import update_connection_data, load_connection_data

        def set_string_port(host_data):
            host_data["hostnames"]["port_test"] = "port_test"
            host_data["ports"]["port_test"] = "2222"

        update_connection_data(set_string_port)

        data = load_connection_data()
        port = data["ports"].get("port_test")
        assert isinstance(port, int)
        assert port == 2222

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict):
                    host_data[key].pop("port_test", None)
        update_connection_data(cleanup)

    def test_thread_safety(self):
        """Test that update_connection_data is thread-safe."""
        import threading
        from sftp_hostdataeditor import update_connection_data, load_connection_data

        results = []

        def worker(idx):
            def modify(host_data):
                name = f"thread_test_{idx}"
                host_data["hostnames"][name] = name
                host_data["usernames"][name] = f"user{idx}"
                host_data["passwords"][name] = f"pass{idx}"
                host_data["ports"][name] = 22
                host_data["key"][name] = ""
            result = update_connection_data(modify)
            results.append(result)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)

        data = load_connection_data()
        for i in range(5):
            assert f"thread_test_{i}" in data["hostnames"]

        def cleanup(host_data):
            for key in host_data:
                if isinstance(host_data[key], dict) and key.startswith("thread_test_"):
                    host_data[key].pop(key, None)
        update_connection_data(cleanup)