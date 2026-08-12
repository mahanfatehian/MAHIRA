from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.updates import UpdateService
from db.backup import BackupService
from ui.theme import (
    BUTTON_STYLE,
    COLORS,
    PRIMARY_BUTTON_STYLE,
    SYSTEM_BUTTON_STYLE,
    TOP_BAR_STYLE,
    card_style,
    set_feature_font,
)
from ui.widgets.number_stepper import NumberStepper


def _set_font(widget: QWidget, size: int, weight: QFont.Weight) -> None:
    set_feature_font(widget, size, weight)


_Stepper = NumberStepper


class _UpdateWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    @Slot()
    def run(self) -> None:
        try:
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            result = UpdateService().check()
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsPage(QWidget):
    settings_changed = Signal()

    def __init__(self, session, _nav=None):
        super().__init__()
        self.setObjectName("SettingsPage")
        self.setProperty("mahiraFeaturePage", True)
        self.session = session
        self.settings = getattr(session, "settings", None)
        self.backups = BackupService(session.repo.db_path)
        self._update_thread = None
        self._update_worker = None
        self._auto_checked = False
        self._loading = False
        self._build()
        self._connect_dirty_signals()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("TopBarCard")
        top_bar.setStyleSheet(TOP_BAR_STYLE)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Settings")
        _set_font(title, 15, QFont.Weight.Black)
        subtitle = QLabel("Study preferences, audio, profiles and learner data")
        subtitle.setWordWrap(True)
        _set_font(subtitle, 9, QFont.Weight.DemiBold)
        subtitle.setStyleSheet(f"color:{COLORS['muted']};")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        top_layout.addLayout(title_col, 1)
        root.addWidget(top_bar)

        study, study_layout = self._section(
            "Study",
            "Shape a session without changing the learning material.",
        )
        self.daily_goal = NumberStepper(5, 200, 5, "daily review goal")
        self.session_limit = NumberStepper(5, 100, 5, "session size")
        self.new_limit = NumberStepper(0, 30, 1, "new cards per session")
        self.strict = QCheckBox("Strict answer matching")
        self.strict.setAccessibleDescription(
            "Require exact stored answers instead of semantic meaning matching where supported"
        )
        study_layout.addWidget(
            self._setting_row(
                "Daily goal",
                "The progress target shown on Today and Progress.",
                self.daily_goal,
                "reviews/day",
            )
        )
        study_layout.addWidget(self._divider())
        study_layout.addWidget(
            self._setting_row(
                "Session size",
                "Maximum cards prepared when a review starts.",
                self.session_limit,
                "cards/session",
            )
        )
        study_layout.addWidget(self._divider())
        study_layout.addWidget(
            self._setting_row(
                "New cards per session",
                "Keep new material from crowding out due reviews.",
                self.new_limit,
                "new/session",
            )
        )
        study_layout.addWidget(self._divider())
        study_layout.addWidget(
            self._setting_row(
                "Answer checking",
                "Turn on when you prefer literal answers over accepted equivalents.",
                self.strict,
            )
        )
        root.addWidget(study)

        display, display_layout = self._section(
            "Audio & display",
            "Tune dictation playback and reading comfort.",
        )
        self.audio_speed = QComboBox()
        self.audio_speed.addItem("Slow · 0.75×", 0.75)
        self.audio_speed.addItem("Normal · 1×", 1.0)
        self.audio_speed.addItem("Fast · 1.25×", 1.25)
        self.audio_speed.setMinimumWidth(150)
        self.audio_autoplay = QCheckBox("Autoplay in dictation")
        self.font_scale = QComboBox()
        for label, value in (
            ("Compact · 90%", 90),
            ("Default · 100%", 100),
            ("Large · 115%", 115),
            ("Extra large · 130%", 130),
        ):
            self.font_scale.addItem(label, value)
        self.font_scale.setMinimumWidth(160)
        self.theme = QComboBox()
        self.theme.addItem("Obsidian", "graphite")
        self.theme.addItem("High contrast", "high_contrast")
        self.theme.setMinimumWidth(160)
        self.reduced_motion = QCheckBox("Reduce non-essential motion")
        for index, row in enumerate(
            (
                self._setting_row(
                    "Speaking speed",
                    "Used by offline pronunciation and audio dictation.",
                    self.audio_speed,
                ),
                self._setting_row(
                    "Dictation",
                    "Play the next prompt as soon as it appears.",
                    self.audio_autoplay,
                ),
                self._setting_row(
                    "Text size",
                    "Scales platform-default text while preserving page hierarchy.",
                    self.font_scale,
                ),
                self._setting_row(
                    "Appearance",
                    "Neutral Obsidian matches the original MAHIRA interface.",
                    self.theme,
                ),
                self._setting_row(
                    "Motion",
                    "Disable celebrations and optional transitions.",
                    self.reduced_motion,
                ),
            )
        ):
            if index:
                display_layout.addWidget(self._divider())
            display_layout.addWidget(row)
        root.addWidget(display)

        profile_data, profile_layout = self._section(
            "Profile & data",
            "Profiles keep independent databases and review schedules.",
        )
        profile_controls = QVBoxLayout()
        profile_controls.setSpacing(8)
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        add_profile = QPushButton("New profile…")
        add_profile.setStyleSheet(BUTTON_STYLE)
        add_profile.clicked.connect(self._new_profile)
        activate_profile = QPushButton("Switch on restart")
        activate_profile.setStyleSheet(SYSTEM_BUTTON_STYLE)
        activate_profile.clicked.connect(self._activate_profile)
        profile_actions = QHBoxLayout()
        profile_actions.setSpacing(8)
        profile_actions.addWidget(add_profile)
        profile_actions.addWidget(activate_profile)
        profile_actions.addStretch(1)
        profile_controls.addWidget(self.profile_combo)
        profile_controls.addLayout(profile_actions)
        self.profile_note = QLabel(
            "Choose a profile, then switch safely on the next app start."
        )
        self.profile_note.setWordWrap(True)
        self.profile_note.setStyleSheet(f"color:{COLORS['muted']};")
        profile_layout.addLayout(profile_controls)
        profile_layout.addWidget(self.profile_note)
        profile_layout.addWidget(self._divider())

        data_actions = QHBoxLayout()
        data_actions.setSpacing(8)
        backup_btn = QPushButton("Create backup")
        backup_btn.setStyleSheet(BUTTON_STYLE)
        backup_btn.clicked.connect(self._backup)
        export_btn = QPushButton("Export…")
        export_btn.setStyleSheet(BUTTON_STYLE)
        export_btn.clicked.connect(self._export)
        restore_btn = QPushButton("Restore…")
        restore_btn.setStyleSheet(BUTTON_STYLE)
        restore_btn.clicked.connect(self._restore)
        data_actions.addWidget(backup_btn)
        data_actions.addWidget(export_btn)
        data_actions.addWidget(restore_btn)
        data_actions.addStretch(1)
        self.backup_status = QLabel()
        self.backup_status.setWordWrap(True)
        self.backup_status.setStyleSheet(f"color:{COLORS['muted']};")
        profile_layout.addLayout(data_actions)
        profile_layout.addWidget(self.backup_status)
        profile_layout.addWidget(self._divider())

        update_row = QHBoxLayout()
        update_row.setSpacing(8)
        self.update_checks = QCheckBox("Check for updates when Settings opens")
        check_now = QPushButton("Check now")
        check_now.setStyleSheet(BUTTON_STYLE)
        check_now.clicked.connect(self._check_updates)
        update_row.addWidget(self.update_checks, 1)
        update_row.addWidget(check_now)
        self.update_status = QLabel()
        self.update_status.setWordWrap(True)
        self.update_status.setStyleSheet(f"color:{COLORS['muted']};")
        profile_layout.addLayout(update_row)
        profile_layout.addWidget(self.update_status)
        root.addWidget(profile_data)

        diagnostics_card, diagnostics_layout = self._section(
            "Diagnostics",
            "Technical details for troubleshooting and support.",
        )
        self.diagnostics_toggle = QPushButton("Show diagnostics")
        self.diagnostics_toggle.setCheckable(True)
        self.diagnostics_toggle.setStyleSheet(BUTTON_STYLE)
        self.diagnostics_toggle.toggled.connect(self._toggle_diagnostics)
        self.diagnostics = QLabel()
        self.diagnostics.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setStyleSheet(
            f"color:{COLORS['muted']};font-family:Consolas,monospace;"
        )
        open_data = QPushButton("Open data folder")
        open_data.setStyleSheet(BUTTON_STYLE)
        open_data.clicked.connect(self._open_data_folder)
        self.diagnostics_body = QWidget()
        body_layout = QVBoxLayout(self.diagnostics_body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(8)
        body_layout.addWidget(self.diagnostics)
        body_layout.addWidget(open_data, 0, Qt.AlignmentFlag.AlignLeft)
        self.diagnostics_body.hide()
        diagnostics_layout.addWidget(
            self.diagnostics_toggle,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        diagnostics_layout.addWidget(self.diagnostics_body)
        root.addWidget(diagnostics_card)

        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        self.save_status = QLabel()
        self.save_status.setStyleSheet(f"color:{COLORS['action_focus']};")
        self.save_button = QPushButton("Save changes")
        self.save_button.setProperty("primary", True)
        self.save_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.save_button.setMinimumWidth(140)
        self.save_button.clicked.connect(self._save)
        save_row.addWidget(self.save_status, 1)
        save_row.addWidget(self.save_button)
        root.addLayout(save_row)
        root.addStretch(1)

    @staticmethod
    def _section(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet(card_style())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        _set_font(heading, 11, QFont.Weight.Black)
        copy = QLabel(description)
        copy.setWordWrap(True)
        copy.setStyleSheet(f"color:{COLORS['muted']};")
        layout.addWidget(heading)
        layout.addWidget(copy)
        layout.addSpacing(2)
        return frame, layout

    @staticmethod
    def _divider() -> QFrame:
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background:{COLORS['divider']};border:none;")
        return divider

    @staticmethod
    def _setting_row(
        title: str,
        description: str,
        control: QWidget,
        unit: str | None = None,
    ) -> QWidget:
        row = QWidget()
        row.setMinimumHeight(54)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(16)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(title)
        heading.setWordWrap(True)
        _set_font(heading, 10, QFont.Weight.Bold)
        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color:{COLORS['muted']};")
        copy.addWidget(heading)
        copy.addWidget(detail)
        control_row = QHBoxLayout()
        control_row.setSpacing(8)
        control_row.addWidget(control)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setWordWrap(True)
            unit_label.setStyleSheet(f"color:{COLORS['muted']};")
            control_row.addWidget(unit_label)
        layout.addLayout(copy, 1)
        layout.addLayout(control_row)
        return row

    def _connect_dirty_signals(self) -> None:
        for stepper in (self.daily_goal, self.session_limit, self.new_limit):
            stepper.valueChanged.connect(self._mark_dirty)
        for checkbox in (
            self.strict,
            self.audio_autoplay,
            self.reduced_motion,
            self.update_checks,
        ):
            checkbox.toggled.connect(self._mark_dirty)
        for combo in (self.audio_speed, self.font_scale, self.theme):
            combo.currentIndexChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        self.save_status.setText("Unsaved changes")
        self.save_status.setStyleSheet(f"color:{COLORS['muted']};")
        self.save_button.setEnabled(True)

    def on_show(self) -> None:
        self._loading = True
        try:
            value = self.settings.value if self.settings is not None else None
            self.daily_goal.setValue(int(getattr(value, "daily_goal", 30)))
            self.session_limit.setValue(int(getattr(value, "session_limit", 30)))
            self.new_limit.setValue(int(getattr(value, "new_card_limit", 8)))
            self.strict.setChecked(bool(getattr(value, "strict_answers", False)))

            speed_index = self.audio_speed.findData(
                float(getattr(value, "audio_speed", 1.0))
            )
            self.audio_speed.setCurrentIndex(max(0, speed_index))
            self.audio_autoplay.setChecked(
                bool(getattr(value, "audio_autoplay", False))
            )

            font_scale = int(getattr(value, "font_scale", 100))
            scale_index = self.font_scale.findData(font_scale)
            if scale_index < 0:
                self.font_scale.addItem(f"Custom · {font_scale}%", font_scale)
                scale_index = self.font_scale.count() - 1
            self.font_scale.setCurrentIndex(scale_index)
            self.reduced_motion.setChecked(
                bool(getattr(value, "reduced_motion", False))
            )
            self.update_checks.setChecked(
                bool(getattr(value, "update_checks", False))
            )
            theme_index = self.theme.findData(getattr(value, "theme", "graphite"))
            self.theme.setCurrentIndex(max(0, theme_index))

            self.profile_combo.clear()
            profile_service = getattr(self.session, "profiles", None)
            if profile_service is not None:
                for profile in profile_service.list():
                    self.profile_combo.addItem(profile.name, profile.slug)
                active = self.profile_combo.findData(
                    getattr(value, "active_profile", "default")
                )
                self.profile_combo.setCurrentIndex(max(0, active))

            backups = self.backups.list()
            self.backup_status.setText(
                f"{len(backups)} managed backup{'s' if len(backups) != 1 else ''} · "
                "newest copies are kept automatically"
            )
            db_path = self.session.repo.db_path
            db_size = db_path.stat().st_size / 1024 / 1024 if db_path.exists() else 0.0
            self.diagnostics.setText(
                f"Python {platform.python_version()} · {platform.system()} {platform.release()}\n"
                f"Database: {db_path}\n"
                f"Database size: {db_size:.1f} MB\n"
                f"Frozen build: {'yes' if getattr(sys, 'frozen', False) else 'no'}"
            )
        finally:
            self._loading = False

        self.save_button.setEnabled(False)
        self.save_status.clear()
        if self.update_checks.isChecked() and not self._auto_checked:
            self._auto_checked = True
            QTimer.singleShot(0, self._check_updates)

    def _save(self) -> None:
        if self.settings is None:
            return
        self.settings.update(
            daily_goal=self.daily_goal.value(),
            session_limit=self.session_limit.value(),
            new_card_limit=self.new_limit.value(),
            strict_answers=self.strict.isChecked(),
            audio_speed=float(self.audio_speed.currentData()),
            audio_autoplay=self.audio_autoplay.isChecked(),
            font_scale=int(self.font_scale.currentData()),
            reduced_motion=self.reduced_motion.isChecked(),
            theme=str(self.theme.currentData()),
            update_checks=self.update_checks.isChecked(),
        )
        self.session.plan.limit = self.session_limit.value()
        self.session.plan.new_limit = self.new_limit.value()
        self.settings_changed.emit()
        self.save_button.setEnabled(False)
        self.save_status.setText("Saved")
        self.save_status.setStyleSheet(f"color:{COLORS['action_focus']};font-weight:800;")

    def _backup(self) -> None:
        try:
            info = self.backups.create("manual")
            self.backup_status.setText(
                f"Backup created: {info.path.name}"
                if info
                else "No database exists to back up yet."
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Backup failed",
                f"The database was not changed.\n\n{exc}",
            )

    def _new_profile(self) -> None:
        service = getattr(self.session, "profiles", None)
        if service is None:
            return
        name, ok = QInputDialog.getText(self, "New learner profile", "Learner name")
        if not ok:
            return
        try:
            profile = service.create(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Profile not created", str(exc))
            return
        self.profile_combo.addItem(profile.name, profile.slug)
        self.profile_combo.setCurrentIndex(self.profile_combo.count() - 1)
        self.profile_note.setText(
            "Profile created. Choose Switch on restart to activate its independent history."
        )

    def _activate_profile(self) -> None:
        if self.settings is None:
            return
        slug = str(self.profile_combo.currentData() or "default")
        if slug != str(self.settings.value.active_profile):
            discard = getattr(self.session, "discard_pending_resume", None)
            if callable(discard):
                discard()
        self.settings.update(active_profile=slug)
        self.profile_note.setText(
            "Profile selected. Restart MAHIRA to switch databases safely."
        )

    def _export(self) -> None:
        default = str(Path.home() / "mahira-learning-backup.db")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Export learning database",
            default,
            "SQLite database (*.db)",
        )
        if not target:
            return
        try:
            info = self.backups.create("export")
            if info is None:
                raise RuntimeError("No learning database exists yet")
            shutil.copy2(info.path, target)
            QMessageBox.information(
                self,
                "Database exported",
                f"A verified copy was saved to:\n{target}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _restore(self) -> None:
        self.backups.backup_dir.mkdir(parents=True, exist_ok=True)
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Restore a managed MAHIRA backup",
            str(self.backups.backup_dir),
            "SQLite database (*.db)",
        )
        if not source:
            return
        answer = QMessageBox.warning(
            self,
            "Restore learning history",
            "This replaces the active profile's learning history. A backup of the current "
            "database will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backups.restore(source)
            discard = getattr(self.session, "discard_pending_resume", None)
            if callable(discard):
                discard()
            QMessageBox.information(
                self,
                "Backup restored",
                "Restart MAHIRA so every page reloads the restored history.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Restore failed",
                f"The active database was left in place.\n\n{exc}",
            )

    def _toggle_diagnostics(self, shown: bool) -> None:
        self.diagnostics_body.setVisible(shown)
        self.diagnostics_toggle.setText(
            "Hide diagnostics" if shown else "Show diagnostics"
        )

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.session.repo.db_path.parent))
        )

    def _check_updates(self) -> None:
        if self._update_thread is not None:
            return
        self.update_status.setText("Checking…")
        thread = QThread(self)
        worker = _UpdateWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._update_ready)
        worker.failed.connect(self._update_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(self._update_finished)
        self._update_thread = thread
        self._update_worker = worker
        thread.start()

    def _update_ready(self, result) -> None:
        if result.available:
            self.update_status.setText(f"Version {result.latest} is available.")
            answer = QMessageBox.question(
                self,
                "Update available",
                f"MAHIRA {result.latest} is available. Open the release page?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(result.page_url))
        else:
            self.update_status.setText(f"You are up to date · {result.current}")

    def _update_failed(self, _message: str) -> None:
        self.update_status.setText(
            "Could not reach the release service. Your offline app is unaffected."
        )

    def _update_finished(self) -> None:
        thread = self._update_thread
        self._update_thread = None
        self._update_worker = None
        if thread is not None:
            thread.deleteLater()

    def _stop_background(self) -> None:
        thread = self._update_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.quit()
