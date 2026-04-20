from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget, QWidgetItem


class FlowLayout(QLayout):
    """
    FlowLayout that works reliably inside QScrollArea.

    Critical fix:
    - DO NOT use isVisible() to decide layout. It can be False during layout passes,
      which causes widgets to never get geometry and appear "missing".
    - If you want to skip, only skip widgets that are explicitly hidden: isHidden().
    """

    def __init__(self, parent: QWidget | None = None, margin: int = 0, hspacing: int = 8, vspacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = int(hspacing)
        self._v = int(vspacing)
        self.setContentsMargins(margin, margin, margin, margin)

    # ---- required QLayout API ----
    def addItem(self, item: QLayoutItem) -> None:
        # Ensure widget is parented to the layout's parentWidget (prevents GC/invisible issues)
        w = None
        try:
            w = item.widget()
        except Exception:
            w = None

        pw = self.parentWidget()
        if isinstance(w, QWidget) and w.parent() is None and pw is not None:
            w.setParent(pw)

        self._items.append(item)
        self.invalidate()
        if pw is not None:
            pw.updateGeometry()
            pw.update()

    def addWidget(self, w: QWidget) -> None:
        pw = self.parentWidget()
        if pw is not None and w.parent() is None:
            w.setParent(pw)
        # Make sure it's not left hidden when added dynamically
        try:
            w.show()
        except Exception:
            pass
        self.addItem(QWidgetItem(w))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            it = self._items.pop(index)
            self.invalidate()
            pw = self.parentWidget()
            if pw is not None:
                pw.updateGeometry()
                pw.update()
            return it
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, int(width), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._items:
            try:
                size = size.expandedTo(item.sizeHint())
            except Exception:
                pass

        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    # ---- layout algorithm ----
    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())

        x = effective.x()
        y = effective.y()
        line_height = 0
        right_limit = effective.x() + max(0, effective.width())

        for item in self._items:
            w = None
            try:
                w = item.widget()
            except Exception:
                w = None

            # ONLY skip explicitly hidden widgets
            if isinstance(w, QWidget) and w.isHidden():
                continue

            try:
                hint = item.sizeHint()
            except Exception:
                continue

            next_x = x + hint.width() + self._h

            if (next_x - self._h) > right_limit and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v
                next_x = x + hint.width() + self._h
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return (y + line_height) - rect.y() + m.bottom()

    def clear(self, *, delete_widgets: bool = True) -> None:
        while self.count():
            it = self.takeAt(0)
            if not it:
                continue
            w = None
            try:
                w = it.widget()
            except Exception:
                w = None
            if delete_widgets and isinstance(w, QWidget):
                w.setParent(None)
                w.deleteLater()

        self.invalidate()
        pw = self.parentWidget()
        if pw is not None:
            pw.updateGeometry()
            pw.update()

    def clear(self, *, delete_widgets: bool = True) -> None:
        while self.count():
            it = self.takeAt(0)
            if not it:
                continue
            w = None
            try:
                w = it.widget()
            except Exception:
                w = None
            if delete_widgets and isinstance(w, QWidget):
                w.setParent(None)
                w.deleteLater()

        self.invalidate()
        pw = self.parentWidget()
        if pw is not None:
            pw.updateGeometry()
            pw.update()