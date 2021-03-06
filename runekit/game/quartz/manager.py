from functools import reduce
from typing import List, Dict, Optional

import Quartz
import ApplicationServices
from PySide2.QtCore import QTimer, Signal, Slot
from PySide2.QtGui import QDesktopServices
from PySide2.QtWidgets import QMessageBox

from .instance import QuartzGameInstance
from ..instance import GameInstance
from ..manager import GameManager

has_prompted_accessibility = False


class QuartzGameManager(GameManager):
    _instances: Dict[int, GameInstance]

    request_accessibility_popup = Signal()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._instances = {}
        self.request_accessibility_popup.connect(self.accessibility_popup)
        self._setup_tap()

        if not ApplicationServices.AXIsProcessTrusted():
            self.accessibility_popup()


    def _setup_tap(self):
        events = [
            Quartz.kCGEventLeftMouseDown,
            Quartz.kCGEventRightMouseDown,
            Quartz.kCGEventKeyDown,
        ]
        events = [Quartz.CGEventMaskBit(e) for e in events]
        event_mask = reduce(lambda a, b: a | b, events)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGAnnotatedSessionEventTap,
            Quartz.kCGTailAppendEventTap,
            Quartz.kCGEventTapOptionListenOnly,  # TODO: Tap keydown synchronously
            event_mask,
            self._on_input,
            None,
        )
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes
        )

    def get_instances(self) -> List[GameInstance]:
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
        )

        for window in windows:
            if window[Quartz.kCGWindowOwnerName] == "rs2client":
                wid = int(window[Quartz.kCGWindowNumber])
                if wid not in self._instances:
                    pid = int(window[Quartz.kCGWindowOwnerPID])
                    self._instances[wid] = QuartzGameInstance(
                        self, wid, pid, parent=self
                    )

        return list(self._instances.values())

    def get_instance_by_pid(self, pid: int) -> Optional[QuartzGameInstance]:
        for instance in self._instances.values():
            if instance.pid == pid:
                return instance

    def _on_input(self, proxy, type_, event, _):
        event_type = Quartz.CGEventGetType(event)
        if event_type == Quartz.kCGEventTapDisabledByUserInput:
            QTimer.singleShot(0, self.accessibility_popup)
            return event
        elif event_type == Quartz.kCGEventTapDisabledByTimeout:
            Quartz.CGEventTapEnable(self._tap, True)
            return event

        nsevent = Quartz.NSEvent.eventWithCGEvent_(event)
        if nsevent.type() == Quartz.NSEventTypeKeyDown:
            front_app = Quartz.NSWorkspace.sharedWorkspace().frontmostApplication()
            instance = self.get_instance_by_pid(front_app.processIdentifier())
        else:
            instance = self._instances.get(nsevent.windowNumber())

        if not instance:
            return event

        # Check for cmd1
        if nsevent.type() == Quartz.NSEventTypeKeyDown:
            if (
                nsevent.keyCode() == 18
                and nsevent.modifierFlags() & Quartz.NSEventModifierFlagCommand
            ):
                instance.alt1_pressed.emit()
                return None

        instance.game_activity.emit()

        return event

    @Slot()
    def accessibility_popup(self):
        global has_prompted_accessibility
        if has_prompted_accessibility:
            return

        has_prompted_accessibility = True
        msgbox = QMessageBox(
            QMessageBox.Warning,
            "Permission required",
            "RuneKit needs Accessibility Access and Screen Recording for global hotkey and game activity monitoring\n\nOpen System Preferences > Security > Privacy > Accessibility to allow this",
            QMessageBox.Open | QMessageBox.Ignore,
        )
        button = msgbox.exec()

        if button == QMessageBox.Open:
            QDesktopServices.openUrl(
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
            )

        # FIXME: Closing this dialog will close the app, idk why
        # I think Qt recognize the dialog as the last app window (which is untrue)
