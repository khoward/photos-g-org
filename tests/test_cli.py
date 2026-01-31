"""
Tests for CLI entry point (gporg.py).
"""

import sys
import importlib
from unittest.mock import MagicMock, patch

import pytest


class TestCLIDefault:
    """Tests for default CLI behavior (TUI)."""

    def test_no_args_launches_tui(self):
        """Test running without arguments launches TUI."""
        import gporg
        importlib.reload(gporg)

        mock_run_tui = MagicMock()

        with patch.object(sys, 'argv', ['gporg']), \
             patch.dict('sys.modules', {'tui': MagicMock(run_tui=mock_run_tui)}):
            gporg.main()

        mock_run_tui.assert_called_once()


class TestCLIWeb:
    """Tests for CLI web server commands."""

    def test_web_starts_server(self):
        """Test 'gporg web' starts web server."""
        import gporg
        importlib.reload(gporg)

        mock_run_server = MagicMock()

        with patch.object(sys, 'argv', ['gporg', 'web']), \
             patch.dict('sys.modules', {'web': MagicMock(run_server=mock_run_server)}):
            gporg.main()

        mock_run_server.assert_called_once_with(port=8099, public=False)

    def test_web_custom_port(self):
        """Test 'gporg web --port' uses custom port."""
        import gporg
        importlib.reload(gporg)

        mock_run_server = MagicMock()

        with patch.object(sys, 'argv', ['gporg', 'web', '--port', '8080']), \
             patch.dict('sys.modules', {'web': MagicMock(run_server=mock_run_server)}):
            gporg.main()

        mock_run_server.assert_called_once_with(port=8080, public=False)

    def test_web_public_flag(self):
        """Test 'gporg web --public' binds to all interfaces."""
        import gporg
        importlib.reload(gporg)

        mock_run_server = MagicMock()

        with patch.object(sys, 'argv', ['gporg', 'web', '--public']), \
             patch.dict('sys.modules', {'web': MagicMock(run_server=mock_run_server)}):
            gporg.main()

        mock_run_server.assert_called_once_with(port=8099, public=True)

    def test_web_stop(self, tmp_path, monkeypatch):
        """Test 'gporg web --stop' stops background server."""
        import gporg
        importlib.reload(gporg)

        # Create fake PID file
        pid_file = tmp_path / 'web.pid'
        pid_file.write_text('12345')
        monkeypatch.setattr(gporg, 'PID_FILE', pid_file)

        with patch.object(sys, 'argv', ['gporg', 'web', '--stop']), \
             patch('os.kill') as mock_kill:
            gporg.main()

        mock_kill.assert_called_once()
        assert not pid_file.exists()

    def test_web_stop_no_server(self, tmp_path, monkeypatch, capsys):
        """Test 'gporg web --stop' when no server running."""
        import gporg
        importlib.reload(gporg)

        pid_file = tmp_path / 'web.pid'
        monkeypatch.setattr(gporg, 'PID_FILE', pid_file)

        with patch.object(sys, 'argv', ['gporg', 'web', '--stop']):
            gporg.main()

        captured = capsys.readouterr()
        assert 'No background' in captured.out


class TestCLIConfig:
    """Tests for CLI config commands."""

    def test_config_sets_credentials(self, capsys, mock_credentials_file):
        """Test 'gporg config <path>' saves credentials."""
        import gporg
        importlib.reload(gporg)

        with patch.object(sys, 'argv', ['gporg', 'config', str(mock_credentials_file)]):
            gporg.main()

        captured = capsys.readouterr()
        assert 'Credentials saved' in captured.out
        assert 'API Key' in captured.out

    def test_config_show(self, capsys, mock_credentials_file):
        """Test 'gporg config --show' displays config."""
        import core
        import gporg
        importlib.reload(gporg)

        # Set up config first
        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        with patch.object(sys, 'argv', ['gporg', 'config', '--show']):
            gporg.main()

        captured = capsys.readouterr()
        assert 'Credentials:' in captured.out

    def test_config_show_unconfigured(self, capsys):
        """Test 'gporg config --show' when not configured."""
        import gporg
        importlib.reload(gporg)

        with patch.object(sys, 'argv', ['gporg', 'config', '--show']):
            gporg.main()

        captured = capsys.readouterr()
        assert 'Not configured' in captured.out

    def test_config_invalid_path(self, capsys):
        """Test 'gporg config' with invalid path."""
        import gporg
        importlib.reload(gporg)

        with patch.object(sys, 'argv', ['gporg', 'config', '/nonexistent/file.json']), \
             pytest.raises(SystemExit) as exc_info:
            gporg.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert 'Error' in captured.out


class TestCLIOrganize:
    """Tests for CLI organize command."""

    def test_organize_requires_config(self, capsys):
        """Test organize fails without config."""
        import gporg
        importlib.reload(gporg)

        with patch.object(sys, 'argv', ['gporg', 'organize', '--year', '2023']), \
             pytest.raises(SystemExit) as exc_info:
            gporg.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert 'No credentials configured' in captured.out

    def test_organize_success(self, capsys, mock_credentials_file):
        """Test successful organize command."""
        import core
        import gporg
        importlib.reload(gporg)

        # Set up config
        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().list().execute.return_value = {'albums': []}
        mock_service.albums().create().execute.return_value = {'id': 'new_album'}
        mock_service.mediaItems().search().execute.side_effect = [
            {'mediaItems': [{'id': 'p1'}, {'id': 'p2'}]},
            {'mediaItems': []},
        ]
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False

        with patch.object(sys, 'argv', ['gporg', 'organize', '--year', '2023']), \
             patch.object(core.Config, 'load_credentials', return_value=mock_creds), \
             patch('core.build', return_value=mock_service):
            gporg.main()

        captured = capsys.readouterr()
        assert 'Done!' in captured.out

    def test_organize_custom_album(self, capsys, mock_credentials_file):
        """Test organize with custom album name."""
        import core
        import gporg
        importlib.reload(gporg)

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().list().execute.return_value = {'albums': []}
        mock_service.albums().create().execute.return_value = {'id': 'new_album'}
        mock_service.mediaItems().search().execute.side_effect = [
            {'mediaItems': [{'id': 'p1'}]},
            {'mediaItems': []},
        ]
        mock_service.albums().batchAddMediaItems().execute.return_value = {}

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False

        with patch.object(sys, 'argv', ['gporg', 'organize', '--year', '2023', '--album', 'My Album']), \
             patch.object(core.Config, 'load_credentials', return_value=mock_creds), \
             patch('core.build', return_value=mock_service):
            gporg.main()

        captured = capsys.readouterr()
        assert 'My Album' in captured.out

    def test_organize_no_photos(self, capsys, mock_credentials_file):
        """Test organize when no photos found."""
        import core
        import gporg
        importlib.reload(gporg)

        config = core.Config()
        config.set_credentials(str(mock_credentials_file))

        mock_service = MagicMock()
        mock_service.albums().list().execute.return_value = {'albums': []}
        mock_service.albums().create().execute.return_value = {'id': 'new_album'}
        mock_service.mediaItems().search().execute.return_value = {'mediaItems': []}

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False

        with patch.object(sys, 'argv', ['gporg', 'organize', '--year', '2023']), \
             patch.object(core.Config, 'load_credentials', return_value=mock_creds), \
             patch('core.build', return_value=mock_service):
            gporg.main()

        captured = capsys.readouterr()
        assert 'No photos found' in captured.out
