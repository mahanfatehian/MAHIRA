from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget


# MAHIRA's established visual language is deliberately neutral: near-black
# canvas, carbon surfaces, quiet hairlines, and colour reserved for actions.
# The compatibility aliases at the bottom keep the feature pages and startup
# splash readable while those components use semantic names.
COLORS: dict[str, str] = {
    "canvas": "#0E0E0E",
    "surface": "#141414",
    "surface_raised": "#181818",
    "surface_sunken": "#101010",
    "surface_secondary": "#1B1B1B",
    "surface_secondary_hover": "#232323",
    "surface_secondary_pressed": "#101010",
    "outline": "#2A2A2A",
    "outline_hover": "#3A3A3A",
    "divider": "#242424",
    "text_primary": "#FFFFFF",
    "text_control": "#F4F4F5",
    "text_secondary": "#9A9A9A",
    "text_disabled": "#686868",
    "action": "#244B36",
    "action_hover": "#2B5B41",
    "action_pressed": "#1B3828",
    "action_border": "#4CAF50",
    "action_focus": "#7AE582",
    "action_text": "#F4FFF7",
    "system": "#163A5C",
    "system_hover": "#1B4B78",
    "system_border": "#24537D",
    "success": "#7AE582",
    "danger": "#421E24",
    "danger_hover": "#55252D",
    "danger_text": "#FFB4BC",
    "selection": "#19324A",
    # Backwards-compatible aliases used by the new feature pages.
    "ink": "#0E0E0E",
    "panel": "#141414",
    "raised": "#1B1B1B",
    "line": "#2A2A2A",
    "paper": "#FFFFFF",
    "muted": "#9A9A9A",
    "green": "#7AE582",
    "red": "#FF9EA8",
}

CONTROL_RADIUS = 10
PANEL_RADIUS = 14
_QSS_FONT_SIZE_RE = re.compile(
    r"(font-size\s*:\s*)([0-9]+(?:\.[0-9]+)?)px",
    re.IGNORECASE,
)


def _bounded_scale(font_scale: int) -> int:
    try:
        requested = int(font_scale)
    except (TypeError, ValueError):
        requested = 100
    return max(85, min(140, requested))


def set_feature_font(widget, point_size: int, weight: QFont.Weight) -> None:
    """Assign a semantic feature-page font that remains scalable.

    A positive point size is installed as a safe fallback for isolated widget
    tests.  The dynamic property lets :func:`app_stylesheet` scale the same
    hierarchy when the learner changes Text size, including after the pages
    have already been constructed.
    """

    base_size = max(1, int(point_size))
    font = QFont(widget.font())
    font.setPointSizeF(float(base_size))
    font.setWeight(weight)
    widget.setFont(font)
    widget.setProperty("mahiraFontPointSize", str(base_size))


def _scale_qss_font_tokens(stylesheet: str, scale: int) -> str:
    def replace(match: re.Match) -> str:
        size = float(match.group(2)) * scale / 100.0
        return f"{match.group(1)}{size:.2f}px"

    return _QSS_FONT_SIZE_RE.sub(replace, stylesheet)


def apply_typography_scale(root: QWidget, font_scale: int = 100) -> None:
    """Scale legacy page typography without changing its visual language.

    Older MAHIRA pages own detailed local QSS and explicit Segoe UI fonts.
    Their original values are cached as tokens, so repeated 85–140% preference
    changes never compound. Semantic feature-page fonts are skipped here.
    """

    scale = _bounded_scale(font_scale)
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        current_qss = widget.styleSheet()
        rendered_qss = widget.property("mahiraRenderedStyleSheet")
        base_qss = widget.property("mahiraBaseStyleSheet")
        if current_qss and current_qss != rendered_qss:
            base_qss = current_qss
            widget.setProperty("mahiraBaseStyleSheet", base_qss)
        if base_qss:
            scaled_qss = _scale_qss_font_tokens(str(base_qss), scale)
            widget.setProperty("mahiraRenderedStyleSheet", scaled_qss)
            if current_qss != scaled_qss:
                widget.setStyleSheet(scaled_qss)

        if widget.property("mahiraFontPointSize") is not None:
            continue
        if base_qss and _QSS_FONT_SIZE_RE.search(str(base_qss)):
            continue
        if not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
            continue

        font = QFont(widget.font())
        point_size = float(font.pointSizeF())
        if point_size <= 0:
            continue
        last_rendered = widget.property("mahiraRenderedPointSize")
        base_point = widget.property("mahiraBasePointSize")
        if base_point is None or (
            last_rendered is not None
            and abs(point_size - float(last_rendered)) > 0.05
        ):
            base_point = point_size
            widget.setProperty("mahiraBasePointSize", base_point)
        scaled_point = max(1.0, float(base_point) * scale / 100.0)
        font.setPointSizeF(scaled_point)
        widget.setFont(font)
        widget.setProperty("mahiraRenderedPointSize", scaled_point)


def apply_application_theme(app, font_scale: int = 100, theme: str = "graphite") -> None:
    """Apply safe application defaults without restyling legacy pages.

    The previous stylesheet set ``font-size`` in pixels on every ``QWidget``.
    Qt represents such a font with ``pointSize() == -1``; a native code path
    then copied that invalid point size and printed the warning seen at startup.
    Scaling the real application font in points keeps the value valid on
    Windows, macOS, and Linux/Wayland and lets page-owned fonts remain intact.
    """

    base = app.property("mahiraBasePointSize")
    if base is None:
        point_size = float(app.font().pointSizeF())
        base = point_size if point_size > 0 else 9.0
        app.setProperty("mahiraBasePointSize", base)

    font = QFont(app.font())
    font.setPointSizeF(max(7.0, float(base) * _bounded_scale(font_scale) / 100.0))
    app.setFont(font)
    app.setStyleSheet(app_stylesheet(font_scale, theme))


def app_stylesheet(font_scale: int = 100, theme: str = "graphite") -> str:
    """Return scoped QSS for new feature pages and application chrome.

    Legacy MAHIRA pages intentionally own their typography and component
    geometry. Every broad rule here therefore begins at a widget carrying the
    ``mahiraFeaturePage`` property. This prevents Settings from flattening the
    mature Setup, Learn, review, table, and conjugation interfaces.
    """

    scale = _bounded_scale(font_scale)
    body_pt = max(8.0, 9.0 * scale / 100.0)
    high_contrast = str(theme).strip().lower() == "high_contrast"
    canvas = "#000000" if high_contrast else COLORS["canvas"]
    surface = "#101010" if high_contrast else COLORS["surface"]
    recessed = "#080808" if high_contrast else COLORS["surface_sunken"]
    control = "#171717" if high_contrast else COLORS["surface_secondary"]
    outline = "#626262" if high_contrast else COLORS["outline"]
    muted = "#C0C0C0" if high_contrast else COLORS["text_secondary"]
    semantic_font_rules = "\n".join(
        (
            'QWidget[mahiraFeaturePage="true"] '
            f'QWidget[mahiraFontPointSize="{base_size}"] {{ '
            f"font-size: {base_size * scale / 100.0:.2f}pt; }}"
        )
        for base_size in range(7, 25)
    )

    return f"""
        /* Only neutral window chrome is application-wide. */
        QMainWindow {{ background-color: {canvas}; }}
        QWidget#MainWindowRoot {{ background-color: {canvas}; }}
        QScrollArea#PageScroll {{ background-color: {canvas}; border: none; }}
        QScrollArea#PageScroll > QWidget > QWidget {{ background-color: {canvas}; }}

        /* Feature-page root. Point units are intentional; never change this
           to px, which recreates Qt's pointSize == -1 warning. */
        QWidget[mahiraFeaturePage="true"] {{
            background-color: {canvas};
            color: {COLORS['text_primary']};
            font-size: {body_pt:.2f}pt;
            selection-background-color: {COLORS['selection']};
            selection-color: {COLORS['text_primary']};
        }}
        QWidget[mahiraFeaturePage="true"] QLabel {{
            background: transparent;
            border: none;
            color: {COLORS['text_primary']};
        }}
        QWidget[mahiraFeaturePage="true"] QLabel:disabled {{
            color: {COLORS['text_disabled']};
        }}

        /* Semantic type roles scale together, so body copy never grows past
           an explicitly sized heading at large-text settings. */
        {semantic_font_rules}

        /* Buttons use the same carbon, forest, and blue roles as review tabs. */
        QWidget[mahiraFeaturePage="true"] QPushButton,
        QWidget[mahiraFeaturePage="true"] QToolButton {{
            background-color: {control};
            color: {COLORS['text_control']};
            border: 1px solid {outline};
            border-radius: {CONTROL_RADIUS}px;
            padding: 8px 12px;
            min-height: 18px;
            font-weight: 800;
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton:hover,
        QWidget[mahiraFeaturePage="true"] QToolButton:hover {{
            background-color: {COLORS['surface_secondary_hover']};
            color: {COLORS['text_primary']};
            border-color: #FFFFFF;
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton:focus,
        QWidget[mahiraFeaturePage="true"] QToolButton:focus {{
            border: 1px solid {COLORS['action_focus']};
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton:pressed,
        QWidget[mahiraFeaturePage="true"] QToolButton:pressed {{
            background-color: {COLORS['surface_secondary_pressed']};
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton:disabled,
        QWidget[mahiraFeaturePage="true"] QToolButton:disabled {{
            background-color: {recessed};
            color: {COLORS['text_disabled']};
            border-color: {outline};
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton[primary="true"] {{
            background-color: {COLORS['action']};
            color: {COLORS['action_text']};
            border-color: {COLORS['action_border']};
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton[primary="true"]:hover {{
            background-color: {COLORS['action_hover']};
            border-color: {COLORS['action_focus']};
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton[system="true"] {{
            background-color: {COLORS['system']};
            color: #FFFFFF;
            border-color: {COLORS['system_border']};
        }}
        QWidget[mahiraFeaturePage="true"] QPushButton[system="true"]:hover {{
            background-color: {COLORS['system_hover']};
            border-color: #FFFFFF;
        }}

        /* Recessed, keyboard-visible fields. */
        QWidget[mahiraFeaturePage="true"] QLineEdit,
        QWidget[mahiraFeaturePage="true"] QTextEdit,
        QWidget[mahiraFeaturePage="true"] QPlainTextEdit,
        QWidget[mahiraFeaturePage="true"] QComboBox,
        QWidget[mahiraFeaturePage="true"] QSpinBox {{
            background-color: {recessed};
            color: {COLORS['text_primary']};
            border: 1px solid {outline};
            border-radius: {CONTROL_RADIUS}px;
            padding: 8px 10px;
            selection-background-color: {COLORS['selection']};
        }}
        QWidget[mahiraFeaturePage="true"] QLineEdit:hover,
        QWidget[mahiraFeaturePage="true"] QTextEdit:hover,
        QWidget[mahiraFeaturePage="true"] QPlainTextEdit:hover,
        QWidget[mahiraFeaturePage="true"] QComboBox:hover,
        QWidget[mahiraFeaturePage="true"] QSpinBox:hover {{
            background-color: {control};
            border-color: {COLORS['outline_hover']};
        }}
        QWidget[mahiraFeaturePage="true"] QLineEdit:focus,
        QWidget[mahiraFeaturePage="true"] QTextEdit:focus,
        QWidget[mahiraFeaturePage="true"] QPlainTextEdit:focus,
        QWidget[mahiraFeaturePage="true"] QComboBox:focus,
        QWidget[mahiraFeaturePage="true"] QSpinBox:focus {{
            border: 1px solid {COLORS['action_focus']};
        }}
        QWidget[mahiraFeaturePage="true"] QComboBox::drop-down {{
            width: 28px;
            border: none;
        }}
        QWidget[mahiraFeaturePage="true"] QComboBox QAbstractItemView {{
            background-color: {surface};
            color: {COLORS['text_primary']};
            border: 1px solid {outline};
            selection-background-color: {COLORS['selection']};
            padding: 5px;
        }}

        QWidget[mahiraFeaturePage="true"] QCheckBox {{
            color: {COLORS['text_primary']};
            spacing: 8px;
            padding: 4px 0;
        }}
        QWidget[mahiraFeaturePage="true"] QCheckBox:focus {{
            color: {COLORS['action_focus']};
        }}
        QWidget[mahiraFeaturePage="true"] QCheckBox::indicator {{
            width: 15px;
            height: 15px;
            background-color: {recessed};
            border: 1px solid {COLORS['outline_hover']};
            border-radius: 4px;
        }}
        QWidget[mahiraFeaturePage="true"] QCheckBox::indicator:hover {{
            border-color: #FFFFFF;
        }}
        QWidget[mahiraFeaturePage="true"] QCheckBox::indicator:checked {{
            background-color: {COLORS['action']};
            border: 2px solid {COLORS['action_focus']};
        }}
        QWidget[mahiraFeaturePage="true"] QCheckBox::indicator:disabled {{
            background-color: {recessed};
            border-color: {outline};
        }}

        QWidget[mahiraFeaturePage="true"] QProgressBar {{
            background-color: {control};
            border: none;
            border-radius: 4px;
            min-height: 8px;
            max-height: 8px;
        }}
        QWidget[mahiraFeaturePage="true"] QProgressBar::chunk {{
            background-color: {COLORS['action_border']};
            border-radius: 4px;
        }}

        QWidget[mahiraFeaturePage="true"] QScrollArea {{
            background: transparent;
            border: none;
        }}
        QWidget[mahiraFeaturePage="true"] QScrollBar:vertical,
        QScrollArea#PageScroll QScrollBar:vertical {{
            background: {canvas};
            width: 9px;
            border: none;
        }}
        QWidget[mahiraFeaturePage="true"] QScrollBar::handle:vertical,
        QScrollArea#PageScroll QScrollBar::handle:vertical {{
            background: {COLORS['outline_hover']};
            min-height: 32px;
            border-radius: 4px;
        }}
        QWidget[mahiraFeaturePage="true"] QScrollBar::add-line,
        QWidget[mahiraFeaturePage="true"] QScrollBar::sub-line,
        QScrollArea#PageScroll QScrollBar::add-line,
        QScrollArea#PageScroll QScrollBar::sub-line {{
            width: 0;
            height: 0;
            border: none;
        }}
        QWidget[mahiraFeaturePage="true"] QScrollBar::add-page,
        QWidget[mahiraFeaturePage="true"] QScrollBar::sub-page,
        QScrollArea#PageScroll QScrollBar::add-page,
        QScrollArea#PageScroll QScrollBar::sub-page {{
            background: transparent;
            border: none;
        }}

        QWidget[mahiraFeaturePage="true"] QToolTip {{
            background-color: {surface};
            color: {COLORS['text_primary']};
            border: 1px solid {outline};
            padding: 6px 8px;
        }}
    """


TOP_BAR_STYLE = f"""
    QFrame#TopBarCard {{
        background-color: {COLORS['surface']};
        border: 1px solid {COLORS['outline']};
        border-radius: 14px;
    }}
"""


def card_style(accent: str | None = None, radius: int = PANEL_RADIUS) -> str:
    """Return a carbon card style; spacing remains the layout's responsibility."""

    edge = accent or COLORS["outline"]
    return f"""
        QFrame {{
            background-color: {COLORS['surface']};
            border: 1px solid {edge};
            border-radius: {int(radius)}px;
        }}
        QFrame QLabel {{
            background: transparent;
            border: none;
            color: {COLORS['text_primary']};
        }}
    """


BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {COLORS['surface_secondary']};
        color: {COLORS['text_control']};
        border: 1px solid {COLORS['outline']};
        border-radius: 10px;
        padding: 8px 12px;
        min-height: 18px;
        font-weight: 800;
    }}
    QPushButton:hover {{
        background-color: {COLORS['surface_secondary_hover']};
        color: #FFFFFF;
        border-color: #FFFFFF;
    }}
    QPushButton:focus {{ border-color: {COLORS['action_focus']}; }}
    QPushButton:pressed {{ background-color: {COLORS['surface_secondary_pressed']}; }}
    QPushButton:disabled {{
        background-color: {COLORS['surface_sunken']};
        color: {COLORS['text_disabled']};
        border-color: {COLORS['outline']};
    }}
"""


PRIMARY_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {COLORS['action']};
        color: {COLORS['action_text']};
        border: 1px solid {COLORS['action_border']};
        border-radius: 12px;
        padding: 9px 14px;
        min-height: 18px;
        font-weight: 900;
    }}
    QPushButton:hover {{
        background-color: {COLORS['action_hover']};
        border-color: {COLORS['action_focus']};
    }}
    QPushButton:focus {{ border-color: {COLORS['action_focus']}; }}
    QPushButton:pressed {{ background-color: {COLORS['action_pressed']}; }}
    QPushButton:disabled {{
        background-color: {COLORS['surface_sunken']};
        color: {COLORS['text_disabled']};
        border-color: {COLORS['outline']};
    }}
"""


SYSTEM_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {COLORS['system']};
        color: #FFFFFF;
        border: 1px solid {COLORS['system_border']};
        border-radius: 10px;
        padding: 8px 12px;
        min-height: 18px;
        font-weight: 800;
    }}
    QPushButton:hover {{
        background-color: {COLORS['system_hover']};
        border-color: #FFFFFF;
    }}
    QPushButton:focus {{ border-color: {COLORS['action_focus']}; }}
    QPushButton:disabled {{
        background-color: {COLORS['surface_sunken']};
        color: {COLORS['text_disabled']};
        border-color: {COLORS['outline']};
    }}
"""


INPUT_STYLE = f"""
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {COLORS['surface_sunken']};
        color: {COLORS['text_primary']};
        border: 1px solid {COLORS['outline']};
        border-radius: 12px;
        padding: 10px 12px;
        selection-background-color: {COLORS['selection']};
    }}
    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
        background-color: {COLORS['surface_secondary']};
        border-color: {COLORS['outline_hover']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {COLORS['action_focus']};
    }}
    QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
        background-color: {COLORS['surface_sunken']};
        color: {COLORS['text_disabled']};
        border-color: {COLORS['outline']};
    }}
"""
