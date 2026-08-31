"""Raw configuration-file editor for InkSim's TOML-backed storage."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..config import Config


def show_config_editor(parent, config):
    """Open a modal editor for the TOML config file."""
    dialog = ConfigEditorDialog(parent, config)
    dialog.exec()


class ConfigEditorDialog(QDialog):
    """Show and edit the TOML configuration path and contents."""

    def __init__(self, parent, config: Config):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Configuration file")
        self.resize(800, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        path_label = QLabel(f"<b>{config.path}</b>", self)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_label)

        hint = QLabel(
            "Edit the TOML file directly. Save writes it back atomically; "
            "changes that affect this session may need an application restart.",
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

        self._reload()

    def _reload(self):
        """Display the current TOML contents."""
        try:
            self._editor.setPlainText(self.config.as_text())
        except Exception as ex:  # noqa: BLE001
            self._editor.setPlainText(f"# Could not read config: {ex}\n")

    def _save(self):
        text = self._editor.toPlainText()
        try:
            self.config.load_text(text)
        except ValueError as ex:
            QMessageBox.critical(self, "Invalid TOML", str(ex))
            return
        except Exception as ex:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to save config: {ex}")
            return
        self.accept()
