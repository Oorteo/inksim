"""Raw configuration-file editor for InkSim's QSettings storage."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


def show_config_editor(parent, config):
    """Open a modal editor for the QSettings backing file."""
    dialog = ConfigEditorDialog(parent, config)
    dialog.exec()


class ConfigEditorDialog(QDialog):
    """Show and edit the QSettings INI file path and contents."""

    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Configuration file")
        self.resize(800, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._path = Path(config.fileName()).resolve()
        path_label = QLabel(f"<b>{self._path}</b>", self)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_label)

        hint = QLabel(
            "Edit the INI file directly. Save writes it back; changes that affect "
            "this session may need an application restart.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._editor = QPlainTextEdit(self)
        self._editor.setFont(QFont("Monospace", 10))
        layout.addWidget(self._editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Close, self
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self._path.is_file():
            try:
                self._editor.setPlainText(
                    self._path.read_text(encoding="utf-8")
                )
            except OSError as ex:
                self._editor.setPlainText(f"# Could not read file: {ex}")
        else:
            self._editor.setPlainText("# Configuration file does not exist yet.\n")

    def _save(self):
        text = self._editor.toPlainText()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text, encoding="utf-8")
            self.config.sync()
        except OSError as ex:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "Error", f"Failed to save config: {ex}")
            return
        self.accept()
