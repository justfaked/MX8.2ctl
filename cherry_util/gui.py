"""Settings window and system tray battery icon (Qt).

One process runs both. `cherry-util tray` starts it with only the tray icon,
`cherry-util gui` also opens the window. Starting it again while it runs
just opens the window of the running instance.
"""

import dataclasses
import sys

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QSizePolicy,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .device import DeviceError, open_device
from .keyboard import Keyboard
from .layout import Key, Layout, load_layout
from .presets import PresetError, PresetStore, apply_preset, current_preset, load_key_colors, set_key_colors
from .protocol import (
    BRIGHTNESS_RANGE,
    DIRECTIONS,
    EFFECT_NAMES,
    EFFECTS,
    HIBERNATE_OFF,
    HIBERNATE_RANGE,
    SLEEP_OFF,
    SLEEP_RANGE,
    USER_SPEED_RANGE,
    BatteryStatus,
    LightingSettings,
    SleepSettings,
    speed_from_user,
    speed_to_user,
)

APP_ID = "cherry-util"
APP_TITLE = "Cherry Keyboard Utility"
BATTERY_POLL_MS = 2 * 60 * 1000
LOW_BATTERY = 25  # the Cherry Utility's "low" level for this keyboard
CRITICAL_BATTERY = 5


def with_keyboard(action):
    """Open the keyboard, run `action(keyboard)` and close it again."""
    with open_device() as device:
        return action(Keyboard(device))


def battery_icon(status: BatteryStatus | None) -> QIcon:
    """A battery outline filled to the current level, with the percentage on top."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    body = QRectF(2, 14, 54, 36)
    outline = QColor("#d0d0d0") if status else QColor("#808080")
    painter.setPen(outline)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 6, 6)
    painter.fillRect(QRectF(57, 24, 5, 16), outline)

    if status:
        if status.charging:
            fill = QColor("#3e9bf5")
        elif status.percent <= CRITICAL_BATTERY:
            fill = QColor("#e5484d")
        elif status.percent <= LOW_BATTERY:
            fill = QColor("#f5a524")
        else:
            fill = QColor("#30a46c")
        inner = body.adjusted(4, 4, -4, -4)
        inner.setWidth(inner.width() * status.percent / 100)
        painter.fillRect(inner, fill)

    font = QFont()
    font.setBold(True)
    font.setPixelSize(30)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    text = str(status.percent) if status else "?"
    painter.drawText(body, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


def show_error(parent, error: Exception) -> None:
    QMessageBox.warning(parent, APP_TITLE, str(error))


class SettingsWindow(QWidget):
    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change  # called after anything was written to the keyboard
        self.setWindowTitle(APP_TITLE)
        self.color = QColor("white")

        self.battery_label = QLabel()
        reload_button = QPushButton("Reload from keyboard")
        reload_button.clicked.connect(self.load)
        header = QHBoxLayout()
        header.addWidget(self.battery_label, 1)
        header.addWidget(reload_button)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._lighting_group())
        layout.addWidget(self._sleep_group())
        layout.addWidget(self._presets_group())

    # --- Layout -------------------------------------------------------------

    def _lighting_group(self) -> QGroupBox:
        self.lights_on = QCheckBox("Lights on")
        self.effect = QComboBox()
        for name in EFFECTS:
            self.effect.addItem(name.replace("-", " ").capitalize(), name)
        self.effect.currentIndexChanged.connect(self._update_enabled)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._pick_color)
        self.rainbow = QCheckBox("Rainbow")
        self.rainbow.toggled.connect(self._update_enabled)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_button, 1)
        color_row.addWidget(self.rainbow)
        self.brightness = self._slider(BRIGHTNESS_RANGE)
        self.speed = self._slider(USER_SPEED_RANGE)
        self.direction = QComboBox()
        for name in DIRECTIONS:
            self.direction.addItem(name.capitalize(), name)
        apply_button = QPushButton("Apply lighting")
        apply_button.clicked.connect(self.apply_lighting)
        keys_button = QPushButton("Per-key colors…")
        keys_button.clicked.connect(self.edit_key_colors)

        form = QFormLayout()
        form.addRow(self.lights_on)
        form.addRow("Effect", self.effect)
        form.addRow("Color", color_row)
        form.addRow("Brightness", self.brightness)
        form.addRow("Speed", self.speed)
        form.addRow("Direction", self.direction)
        form.addRow(apply_button)
        form.addRow(keys_button)
        group = QGroupBox("Lighting")
        group.setLayout(form)
        return group

    def _sleep_group(self) -> QGroupBox:
        self.sleep, self.sleep_off, sleep_row = self._timer_row(SLEEP_RANGE, " s")
        self.hibernate, self.hibernate_off, hibernate_row = self._timer_row(HIBERNATE_RANGE, " min")
        apply_button = QPushButton("Apply sleep settings")
        apply_button.clicked.connect(self.apply_sleep)

        form = QFormLayout()
        form.addRow("Sleep after", sleep_row)
        form.addRow("Hibernate after", hibernate_row)
        form.addRow(apply_button)
        group = QGroupBox("Sleep")
        group.setLayout(form)
        return group

    def _presets_group(self) -> QGroupBox:
        self.presets = QListWidget()
        self.presets.itemDoubleClicked.connect(self.use_preset)
        use_button = QPushButton("Use")
        use_button.clicked.connect(self.use_preset)
        save_button = QPushButton("Save current as…")
        save_button.clicked.connect(self.save_preset)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_preset)
        buttons = QHBoxLayout()
        for button in (use_button, save_button, delete_button):
            buttons.addWidget(button)

        layout = QVBoxLayout()
        layout.addWidget(self.presets)
        layout.addLayout(buttons)
        group = QGroupBox("Presets")
        group.setLayout(layout)
        return group

    @staticmethod
    def _slider(values: range) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(values.start, values.stop - 1)
        slider.setPageStep(1)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(1)
        return slider

    @staticmethod
    def _timer_row(values: range, suffix: str):
        spin = QSpinBox()
        spin.setRange(values.start, values.stop - 1)
        spin.setSuffix(suffix)
        off = QCheckBox("Off")
        off.toggled.connect(lambda checked: spin.setEnabled(not checked))
        row = QHBoxLayout()
        row.addWidget(spin, 1)
        row.addWidget(off)
        return spin, off, row

    def _update_enabled(self) -> None:
        self.color_button.setEnabled(not self.rainbow.isChecked())
        self.direction.setEnabled(self.effect.currentData() == "wave")

    def _set_color(self, color: QColor) -> None:
        self.color = color
        text_color = "black" if color.lightness() > 128 else "white"
        self.color_button.setText(color.name())
        self.color_button.setStyleSheet(f"background-color: {color.name()}; color: {text_color};")

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(self.color, self, "Lighting color")
        if color.isValid():
            self._set_color(color)

    # --- Keyboard <-> widgets -----------------------------------------------

    def load(self) -> None:
        try:
            battery, preset = with_keyboard(lambda kb: (kb.battery(), current_preset(kb)))
        except DeviceError as error:
            self.battery_label.setText(f"Keyboard not reachable: {error}")
            return
        self.battery_label.setText(f"Battery: {battery.percent}%" + (" (charging)" if battery.charging else ""))
        self._show_lighting(preset.lighting)
        self._show_sleep(preset.sleep)
        self._show_presets()

    def _show_lighting(self, lighting: LightingSettings) -> None:
        self.lights_on.setChecked(lighting.enabled)
        name = EFFECT_NAMES.get(lighting.effect)
        if name is not None:
            self.effect.setCurrentIndex(self.effect.findData(name))
        self._set_color(QColor(*lighting.color))
        self.rainbow.setChecked(lighting.rainbow)
        self.brightness.setValue(lighting.brightness)
        self.speed.setValue(speed_to_user(lighting.speed))
        direction = self.direction.findData(next((n for n, v in DIRECTIONS.items() if v == lighting.direction), None))
        if direction >= 0:
            self.direction.setCurrentIndex(direction)
        self._update_enabled()

    def _show_sleep(self, sleep: SleepSettings) -> None:
        self.sleep_off.setChecked(sleep.sleep_seconds == SLEEP_OFF)
        if sleep.sleep_seconds != SLEEP_OFF:
            self.sleep.setValue(sleep.sleep_seconds)
        self.hibernate_off.setChecked(sleep.hibernate_minutes == HIBERNATE_OFF)
        if sleep.hibernate_minutes != HIBERNATE_OFF:
            self.hibernate.setValue(sleep.hibernate_minutes)

    def _show_presets(self) -> None:
        try:
            store = PresetStore()
        except PresetError as error:
            show_error(self, error)
            return
        self.presets.clear()
        for name in sorted(store.presets):
            self.presets.addItem(name + ("  (last used)" if name == store.last_used else ""))
            self.presets.item(self.presets.count() - 1).setData(Qt.ItemDataRole.UserRole, name)

    def _write(self, action) -> None:
        try:
            with_keyboard(action)
        except (DeviceError, PresetError) as error:
            show_error(self, error)
        self.load()
        self.on_change()

    def apply_lighting(self) -> None:
        def action(keyboard: Keyboard) -> None:
            current = keyboard.lighting()
            keyboard.set_lighting(
                dataclasses.replace(
                    current,
                    enabled=self.lights_on.isChecked(),
                    effect=EFFECTS[self.effect.currentData()],
                    color=(self.color.red(), self.color.green(), self.color.blue()),
                    rainbow=self.rainbow.isChecked(),
                    brightness=self.brightness.value(),
                    speed=speed_from_user(self.speed.value()),
                    direction=DIRECTIONS[self.direction.currentData()],
                )
            )

        self._write(action)

    def edit_key_colors(self) -> None:
        dialog = KeyColorsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load()
            self.on_change()

    def apply_sleep(self) -> None:
        wanted = SleepSettings(
            sleep_seconds=SLEEP_OFF if self.sleep_off.isChecked() else self.sleep.value(),
            hibernate_minutes=HIBERNATE_OFF if self.hibernate_off.isChecked() else self.hibernate.value(),
        )
        self._write(lambda keyboard: keyboard.set_sleep_settings(wanted))

    def _selected_preset(self) -> str | None:
        item = self.presets.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def use_preset(self) -> None:
        name = self._selected_preset()
        if name:
            self._write(lambda keyboard: use_preset(keyboard, name))

    def save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Name for the keyboard's current settings:")
        name = name.strip()
        if not ok or not name:
            return
        if not all(c.isalnum() or c in "-_" for c in name):
            show_error(self, ValueError("Use letters, digits, '-' or '_'."))
            return

        def action(keyboard: Keyboard) -> None:
            store = PresetStore()
            store.presets[name] = current_preset(keyboard)
            store.last_used = name
            store.save()

        self._write(action)

    def delete_preset(self) -> None:
        name = self._selected_preset()
        if not name:
            return
        if QMessageBox.question(self, "Delete preset", f"Delete preset '{name}'?") != QMessageBox.StandardButton.Yes:
            return
        try:
            store = PresetStore()
            del store.presets[name]
            if store.last_used == name:
                store.last_used = None
            store.save()
        except PresetError as error:
            show_error(self, error)
        self._show_presets()
        self.on_change()


def use_preset(keyboard: Keyboard, name: str) -> None:
    store = PresetStore()
    apply_preset(keyboard, store.get(name))
    store.last_used = name
    store.save()


class KeyboardView(QWidget):
    """The keyboard drawn from the layout; click keys to select them."""

    def __init__(self, layout: Layout, colors: dict[int, QColor]):
        super().__init__()
        self.layout_ = layout
        self.colors = colors
        self.selected: set[int] = set()
        self.setMinimumSize(QSize(720, int(720 / layout.aspect)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _scale(self) -> tuple[float, float, float]:
        """Picture width and the offset that keeps the aspect ratio, centered."""
        width = min(self.width(), self.height() * self.layout_.aspect)
        height = width / self.layout_.aspect
        return width, (self.width() - width) / 2, (self.height() - height) / 2

    def _shape(self, key: Key) -> QPolygonF:
        width, dx, dy = self._scale()
        height = width / self.layout_.aspect
        points = key.polygon or ((key.x, key.y), (key.x + key.w, key.y), (key.x + key.w, key.y + key.h), (key.x, key.y + key.h))
        return QPolygonF([QPointF(dx + x * width, dy + y * height) for x, y in points])

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        font = QFont()
        font.setPixelSize(max(9, int(self._scale()[0] / 75)))
        painter.setFont(font)
        for key in self.layout_.keys:
            shape = self._shape(key)
            color = self.colors.get(key.index, QColor("black"))
            selected = key.index in self.selected
            painter.setPen(QPen(QColor("#3e9bf5") if selected else QColor("#555555"), 4 if selected else 1))
            painter.setBrush(color)
            painter.drawPolygon(shape)
            painter.setPen(QColor("black") if color.lightness() > 128 else QColor("white"))
            painter.drawText(shape.boundingRect(), Qt.AlignmentFlag.AlignCenter, key.label)

    def mousePressEvent(self, event) -> None:
        for key in self.layout_.keys:
            if self._shape(key).containsPoint(event.position(), Qt.FillRule.OddEvenFill):
                self.selected ^= {key.index}
                self.update()
                return


class KeyColorsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITLE} – per-key colors")
        layout = load_layout()
        try:
            stored = load_key_colors()
        except PresetError as error:
            show_error(self, error)
            stored = {}
        self.view = KeyboardView(layout, {index: QColor(*rgb) for index, rgb in stored.items()})
        self.all_indices = {key.index for key in layout.keys}

        hint = QLabel("Click keys to select them, then pick a color for the selection.")
        color_button = QPushButton("Color for selected…")
        color_button.clicked.connect(self._color_selected)
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._select(self.all_indices))
        select_none = QPushButton("Select none")
        select_none.clicked.connect(lambda: self._select(set()))
        apply_button = QPushButton("Apply to keyboard")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self._apply)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        for button in (color_button, select_all, select_none):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(apply_button)
        buttons.addWidget(close_button)

        box = QVBoxLayout(self)
        box.addWidget(hint)
        box.addWidget(self.view, 1)
        box.addLayout(buttons)

    def _select(self, indices: set[int]) -> None:
        self.view.selected = set(indices)
        self.view.update()

    def _color_selected(self) -> None:
        if not self.view.selected:
            QMessageBox.information(self, APP_TITLE, "Select some keys first.")
            return
        first = self.view.colors.get(next(iter(self.view.selected)), QColor("white"))
        color = QColorDialog.getColor(first, self, "Key color")
        if color.isValid():
            for index in self.view.selected:
                self.view.colors[index] = color
            self._select(set())

    def _apply(self) -> None:
        colors = {
            index: (c.red(), c.green(), c.blue())
            for index, c in self.view.colors.items()
            if (c.red(), c.green(), c.blue()) != (0, 0, 0)
        }

        def action(keyboard: Keyboard) -> None:
            set_key_colors(keyboard, colors)
            lighting = keyboard.lighting()
            if not lighting.enabled or lighting.effect != EFFECTS["custom"]:
                keyboard.set_lighting(dataclasses.replace(lighting, enabled=True, effect=EFFECTS["custom"]))

        try:
            with_keyboard(action)
        except (DeviceError, PresetError) as error:
            show_error(self, error)
            return
        self.accept()


class Tray(QSystemTrayIcon):
    def __init__(self, window: SettingsWindow):
        super().__init__()
        self.window = window
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)
        self.rebuild_menu()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(BATTERY_POLL_MS)
        self.refresh()

    def refresh(self) -> None:
        try:
            status = with_keyboard(lambda keyboard: keyboard.battery())
        except DeviceError as error:
            self.setIcon(battery_icon(None))
            self.setToolTip(f"CHERRY keyboard: {error}")
            return
        self.setIcon(battery_icon(status))
        self.setToolTip(f"CHERRY keyboard: {status.percent}%" + (" (charging)" if status.charging else ""))

    def rebuild_menu(self) -> None:
        self.menu.clear()
        self.menu.addAction("Open settings", self.show_window)
        self.menu.addAction("Refresh battery", self.refresh)
        presets = self.menu.addMenu("Presets")
        try:
            store = PresetStore()
            names = sorted(store.presets)
        except PresetError:
            names = []
        for name in names:
            action = QAction(name, presets, checkable=True, checked=name == store.last_used)
            action.triggered.connect(lambda _checked=False, n=name: self._use(n))
            presets.addAction(action)
        presets.setEnabled(bool(names))
        self.menu.addSeparator()
        self.menu.addAction("Quit", QApplication.quit)

    def _use(self, name: str) -> None:
        try:
            with_keyboard(lambda keyboard: use_preset(keyboard, name))
        except (DeviceError, PresetError) as error:
            show_error(None, error)
        self.changed()

    def changed(self) -> None:
        self.rebuild_menu()
        self.refresh()
        if self.window.isVisible():
            self.window.load()

    def show_window(self) -> None:
        self.window.load()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()


def run(show_window: bool) -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    # Single instance: if one is already running, ask it to open its window.
    socket = QLocalSocket()
    socket.connectToServer(APP_ID)
    if socket.waitForConnected(300):
        if show_window:
            socket.write(b"show")
            socket.waitForBytesWritten(300)
        return
    QLocalServer.removeServer(APP_ID)
    server = QLocalServer()
    server.listen(APP_ID)

    tray = None
    # The window reloads itself after a change; the tray only needs its menu and icon updated.
    window = SettingsWindow(on_change=lambda: tray and (tray.rebuild_menu(), tray.refresh()))
    tray = Tray(window)
    tray.show()

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection.waitForReadyRead(300) and connection.readAll().data() == b"show":
            tray.show_window()

    server.newConnection.connect(on_connection)
    if show_window:
        tray.show_window()
    sys.exit(app.exec())
