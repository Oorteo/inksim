from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QListWidget,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ..formats import get_supported_input_extensions
from .viewer import EmbroideryViewerPanel


class EmbroideryOpenDialog(QDialog):
    """Browse embroidery files with an in-app design preview."""

    def __init__(self, parent, initial_directory, selected_file=None):
        super().__init__(parent)
        self.setWindowTitle("Open embroidery file")
        self.resize(1100, 720)
        self.selected_path = None
        self._modal_result = None
        self.current_directory = Path(initial_directory or Path.cwd()).resolve()
        self.initial_file = Path(selected_file).resolve() if selected_file else None
        self.extensions = get_supported_input_extensions()
        root_layout = QVBoxLayout(self)
        directory_layout = QHBoxLayout()
        self.directory_text = QComboBox(self)
        self.directory_text.setEditable(True)
        directory_layout.addWidget(self.directory_text, 1)
        up_button = QPushButton("Up", self)
        browse_button = QPushButton("Browse...", self)
        directory_layout.addWidget(up_button)
        directory_layout.addWidget(browse_button)
        root_layout.addLayout(directory_layout)
        self.file_list = QListWidget(self)
        preview_container = QWidget(self)
        preview_container.setLayout(QVBoxLayout())
        self.preview = EmbroideryViewerPanel(preview_container, None)
        self.preview.show_grid = False
        self.preview.show_needle = False
        preview_container.layout().addWidget(self.preview)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.file_list)
        splitter.addWidget(preview_container)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        root_layout.addWidget(buttons)
        self.file_list.currentRowChanged.connect(self._on_row_changed)
        self.file_list.itemDoubleClicked.connect(self.open_selected)
        self.directory_text.lineEdit().returnPressed.connect(self.change_directory)
        up_button.clicked.connect(self.go_to_parent_directory)
        browse_button.clicked.connect(self.browse_directory)
        buttons.accepted.connect(self.open_selected)
        buttons.rejected.connect(self.cancel_dialog)
        self.refresh_files()
        QTimer.singleShot(0, self.file_list.setFocus)

    def refresh_files(self):
        if not self.current_directory.is_dir():
            return
        directories = sorted((path for path in self.current_directory.iterdir()
                              if path.is_dir()), key=lambda path: path.name.lower())
        self.directory_text.blockSignals(True)
        self.directory_text.clear()
        self.directory_text.addItems([str(self.current_directory),
                                      *(str(path) for path in directories)])
        self.directory_text.setCurrentText(str(self.current_directory))
        self.directory_text.blockSignals(False)
        files = sorted((path for path in self.current_directory.iterdir()
                        if path.is_file() and path.suffix.lower().lstrip(".")
                        in self.extensions), key=lambda path: path.name.lower())
        self.file_paths = files
        self.file_list.clear()
        self.file_list.addItems([path.name for path in files])
        self._resize_file_list(files)
        self.selected_path = None
        if files:
            selected_index = next((index for index, path in enumerate(files)
                                   if path == self.initial_file), 0)
            self.file_list.setCurrentRow(selected_index)

    def _resize_file_list(self, files):
        widest = max((self.file_list.fontMetrics().horizontalAdvance(path.name)
                      for path in files), default=0)
        self.file_list.setMinimumWidth(min(max(160, widest + 32),
                                           max(160, self.width() - 432)))

    def _on_row_changed(self, row):
        if row < 0 or row >= len(self.file_paths):
            return
        self.selected_path = self.file_paths[row]
        self.preview.load_design(str(self.selected_path), fit_to_screen=True)

    def open_selected(self, event=None):
        if self.selected_path:
            self._finish_modal(QDialog.Accepted)

    def cancel_dialog(self, event=None):
        self._finish_modal(QDialog.Rejected)

    def _finish_modal(self, result):
        if self._modal_result is not None:
            return
        self._modal_result = result
        self.done(result)

    def change_directory(self):
        self.set_directory(self.directory_text.currentText())

    def set_directory(self, directory):
        path = Path(directory).expanduser().resolve()
        if path.is_dir() and path != self.current_directory:
            self.current_directory = path
            self.initial_file = None
            self.refresh_files()

    def go_to_parent_directory(self):
        self.set_directory(self.current_directory.parent)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose directory",
                                                      str(self.current_directory))
        if directory:
            self.set_directory(directory)

    @property
    def path(self):
        return str(self.selected_path) if self.selected_path else ""
