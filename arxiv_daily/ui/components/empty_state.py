"""居中空态组件：大水印 + 提示文案。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class EmptyState(QWidget):
    def __init__(self, mark: str, hint: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        self._mark_label = QLabel(mark)
        self._mark_label.setObjectName("watermark")
        self._mark_label.setAlignment(Qt.AlignCenter)
        self._hint_label = QLabel(hint)
        self._hint_label.setObjectName("hintLabel")
        self._hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._mark_label)
        layout.addWidget(self._hint_label)

    def set_texts(self, mark: str, hint: str):
        self._mark_label.setText(mark)
        self._hint_label.setText(hint)
