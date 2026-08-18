from __future__ import annotations

"""Fast, read-only vocabulary table with self-quiz and pronunciation.

The table deliberately uses Qt's model/view stack instead of one QWidget per
cell.  Only the rows visible in the viewport are painted, so a large Lektion is
as cheap to open as a small one.  Column masking and one-cell reveals live in
the model, while the word-cell delegate paints a compact pronunciation action.
"""

from typing import Any, Optional

from core.vocab_fields import noun_declension_values

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRect,
    QSize,
    QThread,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)


# key, title, accent, relative width
_COLUMNS = [
    ("word", "Vocab", "#66E39A", 3),
    ("article", "Article", "#6B9FFF", 2),
    ("plural", "Plural", "#FFB020", 3),
    ("meaning", "Meaning", "#34D2E0", 4),
    ("pos", "Type", "#8E9AA6", 2),
]
_QUIZ_KEYS = tuple(key for key, _title, _accent, _width in _COLUMNS if key != "pos")
_COLUMN_INDEX = {key: i for i, (key, _title, _accent, _width) in enumerate(_COLUMNS)}
_HIDDEN_GLYPH = "• • •"

# Custom model roles used by the lightweight delegate.
_RAW_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_KEY_ROLE = _RAW_ROLE + 1
_HIDDEN_ROLE = _RAW_ROLE + 2
_REVEALED_ROLE = _RAW_ROLE + 3
_AUDIO_STATE_ROLE = _RAW_ROLE + 4


def _qcolor(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


class _VocabTableModel(QAbstractTableModel):
    """Rows, masking, reveals, and one active audio state."""

    def __init__(self, masked: dict[str, bool], parent: QObject | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, str]] = []
        self._masked = masked
        self._revealed: set[tuple[int, str]] = set()
        self._audio_row = -1
        self._audio_state = "idle"

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        key, title, accent, _width = _COLUMNS[index.column()]
        raw = self.raw_value(index.row(), key)
        hidden = self.is_hidden(index.row(), key)
        revealed = self.is_revealed(index.row(), key)

        if role == Qt.ItemDataRole.DisplayRole:
            if hidden:
                return _HIDDEN_GLYPH
            if key == "pos":
                return raw.capitalize() if raw else "—"
            return raw or "—"
        if role == _RAW_ROLE:
            return raw
        if role == _KEY_ROLE:
            return key
        if role == _HIDDEN_ROLE:
            return hidden
        if role == _REVEALED_ROLE:
            return revealed
        if role == _AUDIO_STATE_ROLE:
            return self._audio_state if key == "word" and index.row() == self._audio_row else "idle"
        if role == Qt.ItemDataRole.ToolTipRole:
            if hidden:
                return f"Reveal {title.lower()}"
            if key == "word" and raw:
                return f"Play pronunciation for {raw} (Space)"
            if key == "pos" and raw.lower() == "verb":
                return "Show full conjugation"
            return raw
        if role == Qt.ItemDataRole.AccessibleTextRole:
            if hidden:
                return f"Hidden {title}. Press Enter to reveal."
            if key == "word" and raw:
                return f"{raw}. Press Space to play pronunciation."
            if key == "pos" and raw.lower() == "verb":
                return "Verb. Press Enter to show full conjugation."
            return raw or f"No {title.lower()}"
        if role == Qt.ItemDataRole.AccessibleDescriptionRole:
            if key == "word" and raw and not hidden:
                return f"German word {raw}; pronunciation is available"
            return ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            if hidden:
                return _qcolor(accent, 175)
            if not raw:
                return QColor("#4E4E4E")
            if key == "word":
                return QColor("#FFFFFF")
            return QColor("#E2E2E2")
        return None

    def headerData(  # noqa: N802 - Qt API
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if orientation != Qt.Orientation.Horizontal or not (0 <= section < len(_COLUMNS)):
            return None
        key, title, accent, _width = _COLUMNS[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return title
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(accent)
        if role == Qt.ItemDataRole.ToolTipRole:
            if key == "pos":
                return "Part of speech; select a verb to open its conjugation"
            action = "Show" if self.column_masked(key) else "Hide"
            return f"{action} the {title} column"
        if role == Qt.ItemDataRole.AccessibleTextRole:
            state = " hidden" if self.column_masked(key) else ""
            return f"{title} column{state}"
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = [
            {key: str(row.get(key, "") or "").strip() for key, *_rest in _COLUMNS}
            for row in rows
        ]
        self._revealed.clear()
        self._audio_row = -1
        self._audio_state = "idle"
        self.endResetModel()

    def row_data(self, row: int) -> dict[str, str]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return {}

    def raw_value(self, row: int, key: str) -> str:
        data = self.row_data(row)
        if key in {"article", "plural"}:
            article, _gender, plural = noun_declension_values(
                data.get("pos"), data.get("article"), None, data.get("plural")
            )
            return article or "" if key == "article" else plural or ""
        return data.get(key, "")

    def column_masked(self, key: str) -> bool:
        return bool(self._masked.get(key, False)) if key in _QUIZ_KEYS else False

    def is_revealed(self, row: int, key: str) -> bool:
        return self.column_masked(key) and (row, key) in self._revealed

    def is_hidden(self, row: int, key: str) -> bool:
        return bool(
            self.column_masked(key)
            and self.raw_value(row, key)
            and (row, key) not in self._revealed
        )

    def word_is_visible(self, row: int) -> bool:
        return bool(self.raw_value(row, "word")) and not self.is_hidden(row, "word")

    def set_column_masked(self, key: str, masked: bool) -> None:
        if key not in _QUIZ_KEYS:
            return
        self._masked[key] = bool(masked)
        self._revealed = {item for item in self._revealed if item[1] != key}
        col = _COLUMN_INDEX[key]
        if self._rows:
            self.dataChanged.emit(
                self.index(0, col),
                self.index(len(self._rows) - 1, col),
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.AccessibleTextRole,
                    _HIDDEN_ROLE,
                    _REVEALED_ROLE,
                ],
            )
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, col, col)

    def toggle_reveal(self, row: int, key: str) -> bool:
        if not self.column_masked(key) or not self.raw_value(row, key):
            return False
        item = (row, key)
        if item in self._revealed:
            self._revealed.remove(item)
        else:
            self._revealed.add(item)
        index = self.index(row, _COLUMN_INDEX[key])
        self.dataChanged.emit(
            index,
            index,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ToolTipRole,
                Qt.ItemDataRole.AccessibleTextRole,
                _HIDDEN_ROLE,
                _REVEALED_ROLE,
            ],
        )
        return True

    def set_audio_state(self, row: int, state: str) -> None:
        state = state if state in {"idle", "busy", "playing", "error"} else "idle"
        old_row = self._audio_row
        self._audio_row = row if 0 <= row < len(self._rows) else -1
        self._audio_state = state
        col = _COLUMN_INDEX["word"]
        for changed_row in {old_row, self._audio_row}:
            if 0 <= changed_row < len(self._rows):
                idx = self.index(changed_row, col)
                self.dataChanged.emit(idx, idx, [_AUDIO_STATE_ROLE])


class _AccentHeader(QHeaderView):
    """Compact, accent-coded header; sections remain clickable mask toggles."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setMinimumHeight(44)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(
            "QHeaderView { background:#101010; border:none; }"
            "QHeaderView::section { background:#101010; border:none; padding:0px; }"
        )

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # noqa: N802
        if not rect.isValid() or not (0 <= logical_index < len(_COLUMNS)):
            return
        key, title, accent, _width = _COLUMNS[logical_index]
        model = self.model()
        masked = bool(getattr(model, "column_masked", lambda _key: False)(key))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cell = rect.adjusted(4, 4, -4, -4)
        painter.setPen(QPen(_qcolor(accent if masked else "#2E2E2E", 255), 1))
        painter.setBrush(_qcolor(accent, 38) if masked else QColor("#1A1A1A"))
        painter.drawRoundedRect(cell, 9, 9)

        painter.setPen(QColor(accent))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Black))
        text_rect = cell.adjusted(10, 0, -8, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        if masked:
            width = painter.fontMetrics().horizontalAdvance(title)
            painter.setPen(_qcolor(accent, 175))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            painter.drawText(
                text_rect.adjusted(width + 8, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "hidden",
            )
        painter.restore()


class _TableDelegate(QStyledItemDelegate):
    """Paints card-like cells and a hit-tested speaker inside word cells."""

    def __init__(self, view: "_VocabTableView"):
        super().__init__(view)
        self._view = view

    @staticmethod
    def audio_rect(rect: QRect) -> QRect:
        size = 28
        return QRect(rect.right() - size - 10, rect.center().y() - size // 2, size, size)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), 48)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        model: _VocabTableModel = index.model()  # type: ignore[assignment]
        key = str(index.data(_KEY_ROLE) or "")
        raw = str(index.data(_RAW_ROLE) or "")
        hidden = bool(index.data(_HIDDEN_ROLE))
        revealed = bool(index.data(_REVEALED_ROLE))
        accent = _COLUMNS[index.column()][2]
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cell = option.rect.adjusted(4, 3, -4, -3)
        base = QColor("#161616" if index.row() % 2 else "#121212")
        border = QColor("#2A2A2A")
        if hidden:
            base = _qcolor(accent, 14)
            border = _qcolor(accent, 145)
        elif revealed:
            base = _qcolor(accent, 31)
            border = QColor(accent)
        elif selected:
            base = QColor("#202720") if key == "word" else QColor("#1B2227")
            border = _qcolor(accent, 205)
        elif hovered:
            border = QColor("#3B3B3B")

        pen = QPen(border, 1)
        if hidden:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(base)
        painter.drawRoundedRect(cell, 8, 8)

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text_rect = cell.adjusted(11, 0, -11, 0)
        if key == "word" and model.word_is_visible(index.row()):
            text_rect.setRight(self.audio_rect(option.rect).left() - 7)

        if key == "pos" and raw.lower() == "verb" and not hidden:
            chip_text = "Verb  ↗"
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Black))
            chip_width = min(text_rect.width(), painter.fontMetrics().horizontalAdvance(chip_text) + 20)
            chip = QRect(text_rect.left(), cell.center().y() - 13, chip_width, 26)
            painter.setPen(QPen(_qcolor("#8AB4FF", 150), 1))
            painter.setBrush(_qcolor("#8AB4FF", 24))
            painter.drawRoundedRect(chip, 7, 7)
            painter.setPen(QColor("#8AB4FF"))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, chip_text)
        else:
            if hidden:
                color = _qcolor(accent, 175)
            elif not raw:
                color = QColor("#4E4E4E")
            elif revealed:
                color = QColor(accent)
            elif key == "word":
                color = QColor("#FFFFFF")
            else:
                color = QColor("#E2E2E2")
            weight = QFont.Weight.Black if key == "word" else QFont.Weight.DemiBold
            painter.setFont(QFont("Segoe UI", 10, weight))
            elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.setPen(color)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        if key == "word" and model.word_is_visible(index.row()):
            self._paint_audio(painter, option, index)

        if option.state & QStyle.StateFlag.State_HasFocus:
            focus = cell.adjusted(1, 1, -1, -1)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_qcolor(accent, 220), 2))
            painter.drawRoundedRect(focus, 8, 8)
        painter.restore()

    def _paint_audio(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        rect = self.audio_rect(option.rect)
        state = str(index.data(_AUDIO_STATE_ROLE) or "idle")
        hovered = self._view.audio_hovered(index)
        if state == "error":
            bg, border, fg = _qcolor("#FF6B6B", 42), QColor("#FF6B6B"), QColor("#FF9B9B")
        elif state == "playing":
            bg, border, fg = _qcolor("#66E39A", 55), QColor("#66E39A"), QColor("#66E39A")
        elif state == "busy":
            bg, border, fg = QColor("#191919"), QColor("#3A3A3A"), QColor("#9A9A9A")
        elif hovered:
            bg, border, fg = _qcolor("#66E39A", 32), QColor("#66E39A"), QColor("#FFFFFF")
        else:
            bg, border, fg = QColor("#1B1B1B"), QColor("#343434"), QColor("#D7D7D7")
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)
        if state == "busy":
            painter.setPen(fg)
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Black))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "…")
            return
        # Draw the speaker ourselves so its contrast is consistent across the
        # Windows/macOS styles (native media icons can be black on a dark view).
        x, y = rect.x(), rect.y()
        speaker = QPainterPath()
        speaker.moveTo(x + 7, y + 11)
        speaker.lineTo(x + 11, y + 11)
        speaker.lineTo(x + 16, y + 7)
        speaker.lineTo(x + 16, y + 21)
        speaker.lineTo(x + 11, y + 17)
        speaker.lineTo(x + 7, y + 17)
        speaker.closeSubpath()
        painter.fillPath(speaker, fg)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(fg, 1.5))
        painter.drawArc(QRect(x + 13, y + 8, 9, 12), -48 * 16, 96 * 16)
        if state == "playing":
            painter.drawArc(QRect(x + 13, y + 5, 13, 18), -45 * 16, 90 * 16)


class _VocabTableView(QTableView):
    audio_requested = Signal(str, int)  # word, row
    conjugation_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio_hover: tuple[int, int] | None = None
        self._delegate = _TableDelegate(self)
        self.setItemDelegate(self._delegate)
        self.setMouseTracking(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(48)
        self.verticalHeader().setMinimumSectionSize(48)
        self.setHorizontalHeader(_AccentHeader(self))
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QTableView { background:#101010; color:#EAEAEA; border:none; outline:none; }"
            "QTableView::item { border:none; padding:0px; }"
            "QScrollBar:vertical { background:#111111; width:10px; margin:2px; }"
            "QScrollBar::handle:vertical { background:#393939; min-height:28px; border-radius:5px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0px; }"
        )

    def model(self) -> _VocabTableModel:  # type: ignore[override]
        return super().model()  # type: ignore[return-value]

    def audio_hovered(self, index: QModelIndex) -> bool:
        return self._audio_hover == (index.row(), index.column())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        total_weight = sum(width for _key, _title, _accent, width in _COLUMNS)
        available = max(360, self.viewport().width())
        assigned = 0
        for col, (_key, _title, _accent, width) in enumerate(_COLUMNS):
            value = available - assigned if col == len(_COLUMNS) - 1 else int(available * width / total_weight)
            self.setColumnWidth(col, max(70, value))
            assigned += value

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        index = self.indexAt(event.position().toPoint())
        old = self._audio_hover
        self._audio_hover = None
        cursor = Qt.CursorShape.ArrowCursor
        if index.isValid():
            key = str(index.data(_KEY_ROLE) or "")
            if key == "word" and self.model().word_is_visible(index.row()):
                if self._delegate.audio_rect(self.visualRect(index)).contains(event.position().toPoint()):
                    self._audio_hover = (index.row(), index.column())
                    cursor = Qt.CursorShape.PointingHandCursor
            if self.model().column_masked(key) and index.data(_RAW_ROLE):
                cursor = Qt.CursorShape.PointingHandCursor
            if key == "pos" and str(index.data(_RAW_ROLE) or "").lower() == "verb":
                cursor = Qt.CursorShape.PointingHandCursor
        if old != self._audio_hover:
            self.viewport().update()
        self.viewport().setCursor(QCursor(cursor))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._audio_hover is not None:
            self._audio_hover = None
            self.viewport().update()
        self.viewport().setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.setCurrentIndex(index)
                key = str(index.data(_KEY_ROLE) or "")
                raw = str(index.data(_RAW_ROLE) or "")
                if (
                    key == "word"
                    and self.model().word_is_visible(index.row())
                    and self._delegate.audio_rect(self.visualRect(index)).contains(event.position().toPoint())
                ):
                    self.audio_requested.emit(raw, index.row())
                    return
                if self.model().toggle_reveal(index.row(), key):
                    return
                if key == "pos" and raw.lower() == "verb":
                    row = self.model().row_data(index.row())
                    self.conjugation_requested.emit(row.get("word", ""), row.get("meaning", ""))
                    return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        index = self.currentIndex()
        if index.isValid() and event.key() in {
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        }:
            key = str(index.data(_KEY_ROLE) or "")
            raw = str(index.data(_RAW_ROLE) or "")
            # Space is the direct pronunciation action when the word is visible.
            if key == "word" and self.model().word_is_visible(index.row()) and event.key() == Qt.Key.Key_Space:
                self.audio_requested.emit(raw, index.row())
                event.accept()
                return
            if self.model().toggle_reveal(index.row(), key):
                event.accept()
                return
            if key == "word" and self.model().word_is_visible(index.row()):
                self.audio_requested.emit(raw, index.row())
                event.accept()
                return
            if key == "pos" and raw.lower() == "verb":
                row = self.model().row_data(index.row())
                self.conjugation_requested.emit(row.get("word", ""), row.get("meaning", ""))
                event.accept()
                return
        super().keyPressEvent(event)


class _TtsWorker(QObject):
    done = Signal(str, str)
    fail = Signal(str, str)

    def __init__(self, service, text: str):
        super().__init__()
        self._service = service
        self._text = text

    @Slot()
    def run(self) -> None:
        try:
            self.done.emit(self._text, str(self._service.generate_wav(self._text)))
        except Exception as exc:  # noqa: BLE001 - surfaced as a non-blocking cell state
            self.fail.emit(self._text, str(exc))


class _LabelProxy:
    """Tiny compatibility shim for older tests; never creates a QWidget."""

    def __init__(self, cell: "_CellProxy"):
        self._cell = cell

    def text(self) -> str:
        return self._cell.display_text()


class _CellProxy:
    """Model-backed cell facade retained for callers that inspected `_cells`."""

    def __init__(self, model: _VocabTableModel, row: int, key: str):
        self._model = model
        self._row = row
        self._key = key
        self._lbl = _LabelProxy(self)

    @property
    def _has(self) -> bool:
        return bool(self._model.raw_value(self._row, self._key))

    def _hidden_now(self) -> bool:
        return self._model.is_hidden(self._row, self._key)

    def display_text(self) -> str:
        return str(self._model.index(self._row, _COLUMN_INDEX[self._key]).data() or "")

    def resize(self, *_args) -> None:
        pass

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - compatibility
        if getattr(event, "button", lambda: Qt.MouseButton.LeftButton)() == Qt.MouseButton.LeftButton:
            self._model.toggle_reveal(self._row, self._key)


class VocabTablePage(QWidget):
    go_back = Signal()
    conjugate_verb = Signal(str, str)

    def __init__(self, session, nav=None):
        super().__init__()
        self.session = session
        self.nav = nav
        self._masked: dict[str, bool] = {key: False for key in _QUIZ_KEYS}
        self._toggle_btns: dict[str, QPushButton] = {}
        self._cells: dict[str, list[_CellProxy]] = {key: [] for key in _QUIZ_KEYS}
        self._pos_cells: list[object] = []
        self._loaded_context: tuple[Any, ...] | None = None

        # Pronunciation is completely lazy: opening/scrolling the table never
        # imports Piper or loads its model.  Shared core caching makes the first
        # click on later audio pages reuse the same voice.
        self._model_mgr = None
        self._pron = None
        self._play_svc = None
        self._audio_thread: Optional[QThread] = None
        self._audio_worker: Optional[_TtsWorker] = None
        self._synth_request: tuple[str, int] | None = None
        self._pending_request: tuple[str, int] | None = None
        self._active_audio_row = -1

        self.setObjectName("VocabTablePage")
        self.setFont(QFont("Segoe UI", 10))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "#VocabTablePage { background-color:#0E0E0E; }"
            "#VocabTablePage QLabel { background:transparent; }"
        )
        self._build_ui()
        self._load(force=True)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBarCard")
        self.top_bar.setStyleSheet(
            "QFrame#TopBarCard { background:#141414; border:1px solid #2A2A2A; border-radius:14px; }"
        )
        tb = QHBoxLayout(self.top_bar)
        tb.setContentsMargins(16, 12, 16, 12)
        tb.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.page_title = QLabel("Vocab Table")
        self.page_title.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:20px; font-weight:950; border:none; }"
        )
        self.page_subtitle = QLabel("Self-quiz the vocabulary, column by column")
        self.page_subtitle.setStyleSheet(
            "QLabel { color:#9A9A9A; font-size:11px; font-weight:700; border:none; }"
        )
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        tb.addLayout(title_col)
        tb.addStretch(1)
        self.count_chip = QLabel("0 words")
        self.count_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_chip.setStyleSheet(
            "QLabel { color:#FFFFFF; font-size:12px; font-weight:800; background:#1A1A1A; "
            "border:1px solid #2E2E2E; border-radius:8px; padding:6px 12px; }"
        )
        self.back_btn = QPushButton("← Back")
        self.back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.back_btn.setStyleSheet(
            "QPushButton { background:#1B1B1B; color:#FFFFFF; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:8px 12px; font-weight:800; font-size:12px; }"
            "QPushButton:hover { border:1px solid #FFFFFF; background:#232323; }"
        )
        self.back_btn.clicked.connect(self.go_back.emit)
        tb.addWidget(self.count_chip)
        tb.addWidget(self.back_btn)
        outer.addWidget(self.top_bar)

        self.controls = QFrame()
        self.controls.setObjectName("ControlsCard")
        self.controls.setStyleSheet(
            "QFrame#ControlsCard { background:#131313; border:1px solid #262626; border-radius:14px; }"
        )
        cc = QVBoxLayout(self.controls)
        cc.setContentsMargins(14, 12, 14, 12)
        cc.setSpacing(10)
        hint = QLabel(
            "Hide a column to quiz yourself. Reveal any cell to check it; use the listening button beside a visible German word."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "QLabel { color:#8C8C8C; font-size:11px; font-weight:600; border:none; }"
        )
        cc.addWidget(hint)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for key, _title, _accent, _width in _COLUMNS:
            if key == "pos":
                continue
            button = QPushButton()
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(34)
            button.clicked.connect(lambda _checked=False, k=key: self._toggle_column(k))
            self._toggle_btns[key] = button
            btn_row.addWidget(button, 1)
        self.show_all_btn = QPushButton("Show all")
        self.show_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.show_all_btn.setMinimumHeight(34)
        self.show_all_btn.setStyleSheet(
            "QPushButton { background:#1B1B1B; color:#CFCFCF; border:1px solid #2E2E2E; "
            "border-radius:10px; padding:7px 14px; font-weight:800; font-size:12px; }"
            "QPushButton:hover { border:1px solid #FFFFFF; color:#FFFFFF; }"
        )
        self.show_all_btn.clicked.connect(self._show_all)
        btn_row.addWidget(self.show_all_btn)
        cc.addLayout(btn_row)
        outer.addWidget(self.controls)

        self.table_card = QFrame()
        self.table_card.setObjectName("TableCard")
        self.table_card.setStyleSheet(
            "QFrame#TableCard { background:#101010; border:1px solid #262626; border-radius:16px; }"
        )
        table_layout = QVBoxLayout(self.table_card)
        table_layout.setContentsMargins(8, 8, 8, 8)
        table_layout.setSpacing(0)
        self._table_model = _VocabTableModel(self._masked, self)
        self.table = _VocabTableView()
        self.table.setModel(self._table_model)
        self.table.audio_requested.connect(self._dispatch_word_audio)
        self.table.conjugation_requested.connect(self.conjugate_verb.emit)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.setAccessibleName("Vocabulary study table")
        self.table.setAccessibleDescription(
            "Use arrow keys to move. Enter reveals a hidden cell; Space plays a visible German word."
        )
        # `scroll` remains as a compatibility alias for earlier callers/tests.
        self.scroll = self.table
        table_layout.addWidget(self.table, 1)
        self.empty_lbl = QLabel("No vocabulary in this Lektion yet.")
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_lbl.setStyleSheet(
            "QLabel { color:#6B6B6B; font-size:13px; font-weight:700; border:none; padding:28px; }"
        )
        self.empty_lbl.hide()
        table_layout.addWidget(self.empty_lbl)
        outer.addWidget(self.table_card, 1)

        for key in _QUIZ_KEYS:
            self._sync_toggle(key)

    # --------------------------------------------------------------- data
    def _context_signature(self) -> tuple[Any, ...]:
        state = getattr(self.session, "state", None)
        if state is not None:
            return (
                str(getattr(state, "level", "") or "").upper().strip(),
                str(getattr(state, "book_slug", "") or "").strip(),
                int(getattr(state, "lektion_number", 0) or 0),
            )
        try:
            return ("context", str(self.session.context_label() or ""))
        except Exception:
            return ("session", id(self.session))

    def on_show(self) -> None:
        self._load()

    def _load(self, *, force: bool = False) -> None:
        signature = self._context_signature()
        try:
            context_label = str(self.session.context_label() or "")
        except Exception:
            context_label = ""
        self.page_subtitle.setText(context_label or "Self-quiz the vocabulary, column by column")
        if not force and signature == self._loaded_context:
            return

        self._stop_audio()
        try:
            rows = self.session.vocab_table_rows()
        except Exception:
            rows = []
        self._loaded_context = signature
        self._table_model.set_rows(rows)
        self._cells = {
            key: [_CellProxy(self._table_model, row, key) for row in range(len(rows))]
            for key in _QUIZ_KEYS
        }
        self._pos_cells = [object() for _row in rows]
        count = len(rows)
        self.count_chip.setText("1 word" if count == 1 else f"{count} words")
        for key in _QUIZ_KEYS:
            self._table_model.set_column_masked(key, self._masked[key])
            self._sync_toggle(key)
        has_rows = count > 0
        self.table.setVisible(has_rows)
        self.empty_lbl.setVisible(not has_rows)
        self.controls.setEnabled(has_rows)

    def refresh(self) -> None:
        """Explicitly reload the current deck after an external data change."""
        self._load(force=True)

    # ------------------------------------------------------------- masking
    def _on_header_clicked(self, section: int) -> None:
        if 0 <= section < len(_COLUMNS):
            key = _COLUMNS[section][0]
            if key in _QUIZ_KEYS:
                self._toggle_column(key)

    def _toggle_column(self, key: str) -> None:
        if key not in _QUIZ_KEYS:
            return
        self._masked[key] = not self._masked.get(key, False)
        if key == "word" and self._masked[key]:
            self._stop_audio()
        self._apply_column(key)

    def _show_all(self) -> None:
        for key in _QUIZ_KEYS:
            self._masked[key] = False
            self._apply_column(key)

    def _apply_column(self, key: str) -> None:
        self._table_model.set_column_masked(key, bool(self._masked.get(key, False)))
        self._sync_toggle(key)
        self.table.horizontalHeader().viewport().update()

    def _sync_toggle(self, key: str) -> None:
        button = self._toggle_btns.get(key)
        if button is None:
            return
        _key, title, accent, _width = _COLUMNS[_COLUMN_INDEX[key]]
        on = bool(self._masked.get(key, False))
        button.setText(f"{'Show' if on else 'Hide'} {title}")
        button.setAccessibleName(f"{'Show' if on else 'Hide'} {title} column")
        if on:
            button.setStyleSheet(
                f"QPushButton {{ background:{accent}; color:#0B0B0B; border:1px solid {accent}; "
                "border-radius:10px; padding:7px 12px; font-weight:900; font-size:12px; }"
                "QPushButton:hover { border:1px solid #FFFFFF; }"
            )
        else:
            button.setStyleSheet(
                f"QPushButton {{ background:#1B1B1B; color:{accent}; border:1px solid #2E2E2E; "
                "border-radius:10px; padding:7px 12px; font-weight:800; font-size:12px; }"
                f"QPushButton:hover {{ border:1px solid {accent}; background:#202020; }}"
            )

    # --------------------------------------------------------------- audio
    @Slot(str, int)
    def _dispatch_word_audio(self, text: str, row: int) -> None:
        # Resolve dynamically so integrations/tests can replace the player
        # without reconnecting the virtualized view's signal.
        self._play_word(text, row)

    def _ensure_audio(self) -> bool:
        if self._play_svc is not None:
            return True
        try:
            from core.audio import PiperModelManager, PlaybackService, PronunciationService

            self._model_mgr = PiperModelManager()
            self._pron = PronunciationService(self._model_mgr)
            self._play_svc = PlaybackService(self)
            self._play_svc.started.connect(self._on_play_started)
            self._play_svc.finished.connect(self._on_play_finished)
            self._play_svc.failed.connect(self._on_play_failed)
            return True
        except Exception:
            self._play_svc = None
            return False

    @Slot(str, int)
    def _play_word(self, text: str, row: int) -> None:
        text = (text or "").strip()
        if not self.isVisible() or not text or not self._table_model.word_is_visible(row):
            return
        if not self._ensure_audio():
            self._set_audio_error(row)
            return
        # Cancel pending/loading/playing audio before switching the active row;
        # a synchronous `finished` signal then resets the OLD row, never the new.
        if self._play_svc is not None:
            self._play_svc.stop()
        self._active_audio_row = row
        self._table_model.set_audio_state(row, "busy")

        request = (text, row)
        if self._audio_thread is not None and self._audio_thread.isRunning():
            # Keep only the learner's latest click; the in-flight render safely
            # finishes into the shared cache and is then superseded.
            self._pending_request = None if request == self._synth_request else request
            return
        self._pending_request = None
        self._start_audio_request(text, row)

    def _start_audio_request(self, text: str, row: int) -> None:
        if self._pron is None or self._play_svc is None:
            self._set_audio_error(row)
            return
        self._synth_request = (text, row)
        self._active_audio_row = row
        self._table_model.set_audio_state(row, "busy")
        try:
            cached = self._pron.get_cached_path(text)
            if cached.exists():
                self._play_svc.stop()
                self._play_svc.play_file(cached)
                return
        except Exception:
            pass

        self._audio_thread = QThread(self)
        self._audio_worker = _TtsWorker(self._pron, text)
        self._audio_worker.moveToThread(self._audio_thread)
        self._audio_thread.started.connect(self._audio_worker.run)
        self._audio_worker.done.connect(self._on_tts_done)
        self._audio_worker.fail.connect(self._on_tts_fail)
        self._audio_worker.done.connect(self._audio_thread.quit)
        self._audio_worker.fail.connect(self._audio_thread.quit)
        self._audio_worker.done.connect(self._audio_worker.deleteLater)
        self._audio_worker.fail.connect(self._audio_worker.deleteLater)
        self._audio_thread.finished.connect(self._on_thread_finished)
        self._audio_thread.finished.connect(self._audio_thread.deleteLater)
        self._audio_thread.start()

    @Slot(str, str)
    def _on_tts_done(self, text: str, path: str) -> None:
        request = self._synth_request
        if request is None or text != request[0]:
            return
        row = request[1]
        latest = self._pending_request
        if latest is not None and latest != request:
            return
        if not self.isVisible() or not self._table_model.word_is_visible(row):
            self._table_model.set_audio_state(row, "idle")
            return
        if self._play_svc is not None:
            self._play_svc.play_file(path)

    @Slot(str, str)
    def _on_tts_fail(self, text: str, _message: str) -> None:
        request = self._synth_request
        if request is not None and text == request[0] and self._pending_request is None:
            self._set_audio_error(request[1])

    @Slot()
    def _on_thread_finished(self) -> None:
        self._audio_thread = None
        self._audio_worker = None
        self._synth_request = None
        pending = self._pending_request
        self._pending_request = None
        if pending is not None and self.isVisible():
            QTimer.singleShot(
                0,
                lambda req=pending: self._start_audio_request(*req)
                if self.isVisible()
                and self._active_audio_row == req[1]
                and self._table_model.word_is_visible(req[1])
                else None,
            )

    @Slot(str)
    def _on_play_started(self, _path: str) -> None:
        self._table_model.set_audio_state(self._active_audio_row, "playing")

    @Slot()
    def _on_play_finished(self) -> None:
        self._table_model.set_audio_state(self._active_audio_row, "idle")

    @Slot(str)
    def _on_play_failed(self, _message: str) -> None:
        self._set_audio_error(self._active_audio_row)

    def _set_audio_error(self, row: int) -> None:
        self._active_audio_row = row
        self._table_model.set_audio_state(row, "error")
        QTimer.singleShot(2200, lambda r=row: self._clear_audio_error(r))

    def _clear_audio_error(self, row: int) -> None:
        index = self._table_model.index(row, _COLUMN_INDEX["word"])
        if (
            self._active_audio_row == row
            and index.isValid()
            and index.data(_AUDIO_STATE_ROLE) == "error"
        ):
            self._table_model.set_audio_state(row, "idle")

    def _stop_audio(self) -> None:
        self._pending_request = None
        self._synth_request = None
        if self._play_svc is not None:
            try:
                self._play_svc.stop()
            except Exception:
                pass
        self._table_model.set_audio_state(-1, "idle")
        self._active_audio_row = -1

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._stop_audio()
        super().hideEvent(event)

    # ---------------------------------------------------------- focus mode
    def set_focus_mode(self, on: bool) -> None:
        self.top_bar.setVisible(not bool(on))
        self.controls.setVisible(not bool(on))
