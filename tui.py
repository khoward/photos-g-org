"""
Rich Terminal User Interface for Google Photos Organizer.
Built with Textual framework.
"""

from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Input, Select, Switch,
    ProgressBar, Label, DirectoryTree, ListView, ListItem
)
from textual.screen import Screen
from textual.binding import Binding
from textual import work

from core import Config, PhotosService, get_available_years


class ConfigScreen(Screen):
    """Screen for configuring credentials."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Credentials Configuration", classes="title"),
            Static("Enter the path to your Google service account JSON file:", classes="label"),
            Input(
                placeholder="~/.config/gporg/service-account.json",
                id="creds-path"
            ),
            Horizontal(
                Button("Browse", id="browse-btn", variant="default"),
                Button("Save & Continue", id="save-btn", variant="primary"),
                classes="button-row"
            ),
            Static("", id="status-msg", classes="status"),
            id="config-container",
            classes="glass-panel"
        )
        yield Footer()

    def on_mount(self) -> None:
        config = Config()
        if config.credentials_path:
            self.query_one("#creds-path", Input).value = config.credentials_path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_config()
        elif event.button.id == "browse-btn":
            self.app.push_screen(FileBrowserScreen())

    def _save_config(self) -> None:
        path = self.query_one("#creds-path", Input).value
        path = str(Path(path).expanduser())
        status = self.query_one("#status-msg", Static)

        if not Path(path).exists():
            status.update("[red]File not found![/red]")
            return

        config = Config()
        config.set_credentials(path)
        status.update("[green]Saved![/green]")
        self.app.pop_screen()


class FileBrowserScreen(Screen):
    """Simple file browser for selecting credentials."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Select Credentials File", classes="title"),
            DirectoryTree(str(Path.home()), id="file-tree"),
            Horizontal(
                Button("Cancel", id="cancel-btn"),
                Button("Select", id="select-btn", variant="primary"),
                classes="button-row"
            ),
            id="browser-container",
            classes="glass-panel"
        )
        yield Footer()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        if str(event.path).endswith('.json'):
            # Go back and set the path
            self.app.pop_screen()
            config_screen = self.app.screen
            if hasattr(config_screen, 'query_one'):
                try:
                    config_screen.query_one("#creds-path", Input).value = str(event.path)
                except Exception:
                    pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.app.pop_screen()


class MainScreen(Screen):
    """Main screen for organizing photos."""

    BINDINGS = [
        Binding("c", "configure", "Configure"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            Container(
                Static("Google Photos Organizer", classes="app-title"),

                # Credentials card
                Container(
                    Static("Credentials", classes="card-title"),
                    Horizontal(
                        Static("Status:", classes="label"),
                        Static("Not configured", id="creds-status"),
                    ),
                    Button("Configure", id="config-btn", variant="default"),
                    classes="glass-card"
                ),

                # Year filter card
                Container(
                    Static("Filter by Year", classes="card-title"),
                    Select(
                        [(str(y), y) for y in get_available_years()],
                        id="year-select",
                        prompt="Select year"
                    ),
                    classes="glass-card"
                ),

                # Album card
                Container(
                    Static("Destination Album", classes="card-title"),
                    Horizontal(
                        Switch(id="create-new-switch", value=True),
                        Static("Create new album", classes="label"),
                    ),
                    Input(placeholder="Album name", id="new-album-name"),
                    Select([], id="existing-album", prompt="Select existing album"),
                    Button("Refresh Albums", id="refresh-albums-btn", variant="default"),
                    classes="glass-card"
                ),

                # Options card
                Container(
                    Static("Options", classes="card-title"),
                    Horizontal(
                        Switch(id="skip-existing-switch", value=True),
                        Static("Skip photos already in album", classes="label"),
                    ),
                    classes="glass-card"
                ),

                # Action button
                Button("Organize Photos", id="organize-btn", variant="primary", classes="big-button"),

                # Progress card
                Container(
                    Static("Progress", classes="card-title"),
                    ProgressBar(id="progress-bar", total=100, show_eta=False),
                    Static("Ready", id="progress-status"),
                    classes="glass-card"
                ),

                id="main-container"
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self._update_config_status()

    def _update_config_status(self) -> None:
        config = Config()
        status = self.query_one("#creds-status", Static)
        if config.is_configured:
            status.update("[green]Configured[/green]")
            self._load_albums()
        else:
            status.update("[red]Not configured[/red]")

    @work(thread=True)
    def _load_albums(self) -> None:
        config = Config()
        if not config.is_configured:
            return

        try:
            service = PhotosService(config.credentials_path)
            albums = service.list_albums()

            # Update select widget on main thread
            self.app.call_from_thread(
                self._update_album_select,
                albums
            )
        except Exception as e:
            self.app.call_from_thread(
                self._show_error,
                f"Error loading albums: {e}"
            )

    def _update_album_select(self, albums: list) -> None:
        select = self.query_one("#existing-album", Select)
        options = [(a.get('title', 'Untitled'), a['id']) for a in albums]
        select.set_options(options)

    def _show_error(self, message: str) -> None:
        status = self.query_one("#progress-status", Static)
        status.update(f"[red]{message}[/red]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-btn":
            self.app.push_screen(ConfigScreen())
        elif event.button.id == "refresh-albums-btn":
            self._load_albums()
        elif event.button.id == "organize-btn":
            self._start_organize()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "create-new-switch":
            new_album_input = self.query_one("#new-album-name", Input)
            existing_select = self.query_one("#existing-album", Select)

            if event.value:
                new_album_input.display = True
                existing_select.display = False
            else:
                new_album_input.display = False
                existing_select.display = True

    def action_configure(self) -> None:
        self.app.push_screen(ConfigScreen())

    def action_quit(self) -> None:
        self.app.exit()

    @work(thread=True)
    def _start_organize(self) -> None:
        config = Config()
        if not config.is_configured:
            self.app.call_from_thread(self._show_error, "Please configure credentials first")
            return

        # Get values
        year_select = self.query_one("#year-select", Select)
        if year_select.value == Select.BLANK:
            self.app.call_from_thread(self._show_error, "Please select a year")
            return

        year = int(year_select.value)
        create_new = self.query_one("#create-new-switch", Switch).value
        skip_existing = self.query_one("#skip-existing-switch", Switch).value

        if create_new:
            album_name = self.query_one("#new-album-name", Input).value
            if not album_name:
                album_name = f"Photos from {year}"
            album_id = None
        else:
            album_select = self.query_one("#existing-album", Select)
            if album_select.value == Select.BLANK:
                self.app.call_from_thread(self._show_error, "Please select an album")
                return
            album_id = album_select.value
            album_name = None

        try:
            service = PhotosService(config.credentials_path)

            # Update status
            self.app.call_from_thread(
                self._update_progress,
                0, 100, "Finding/creating album..."
            )

            # Get or create album
            if album_id:
                target_album_id = album_id
            else:
                target_album_id = service.get_or_create_album(album_name)

            # Search for photos
            self.app.call_from_thread(
                self._update_progress,
                0, 100, f"Searching for photos from {year}..."
            )

            photos = service.search_photos_by_year(year)
            photo_ids = [p['id'] for p in photos]

            if not photo_ids:
                self.app.call_from_thread(
                    self._update_progress,
                    100, 100, f"No photos found for {year}"
                )
                return

            # Add to album
            total = len(photo_ids)
            self.app.call_from_thread(
                self._update_progress,
                0, total, f"Adding {total} photos to album..."
            )

            for added, total in service.add_to_album(
                target_album_id, photo_ids, skip_existing=skip_existing
            ):
                self.app.call_from_thread(
                    self._update_progress,
                    added, total, f"Added {added}/{total} photos..."
                )

            self.app.call_from_thread(
                self._update_progress,
                total, total, f"Done! Added photos to album."
            )

        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))

    def _update_progress(self, current: int, total: int, message: str) -> None:
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        status = self.query_one("#progress-status", Static)

        if total > 0:
            progress_bar.update(total=total, progress=current)
        status.update(message)


class PhotosOrganizerApp(App):
    """Main TUI application."""

    CSS = """
    Screen {
        background: $surface;
    }

    .app-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding: 1 0;
        width: 100%;
    }

    .glass-card {
        background: $panel;
        border: solid $primary-lighten-2;
        margin: 1 2;
        padding: 1 2;
    }

    .glass-panel {
        background: $panel;
        border: solid $primary-lighten-2;
        margin: 2;
        padding: 2;
    }

    .card-title {
        text-style: bold;
        color: $primary-lighten-1;
        margin-bottom: 1;
    }

    .title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    .label {
        margin-left: 1;
    }

    .status {
        margin-top: 1;
        text-align: center;
    }

    .button-row {
        margin-top: 1;
        align: center middle;
    }

    .button-row Button {
        margin: 0 1;
    }

    .big-button {
        margin: 2;
        width: 100%;
    }

    #main-container {
        padding: 1;
    }

    #config-container {
        width: 60;
        height: auto;
        margin: 4 auto;
    }

    #browser-container {
        width: 80%;
        height: 80%;
        margin: 2 auto;
    }

    #file-tree {
        height: 100%;
        margin: 1 0;
    }

    Input {
        margin: 1 0;
    }

    Select {
        margin: 1 0;
    }

    Switch {
        margin-right: 1;
    }

    ProgressBar {
        margin: 1 0;
    }

    #progress-status {
        text-align: center;
        color: $text-muted;
    }
    """

    TITLE = "Google Photos Organizer"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "toggle_dark", "Dark Mode"),
    ]

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark


def run_tui():
    """Run the TUI application."""
    app = PhotosOrganizerApp()
    app.run()


if __name__ == '__main__':
    run_tui()
