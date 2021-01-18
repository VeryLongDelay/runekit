import logging
from typing import List, Dict

from PySide2.QtCore import QThread, Slot, Signal, QObject
from Xlib import X
from Xlib.display import Display
from Xlib.ext import xinput, ge
from Xlib.protocol import event
from Xlib.xobject.drawable import Window
import Xlib.threaded

from runekit.game import GameManager
from .instance import GameInstance, X11GameInstance


class X11EventWorker(QObject):
    on_active_changed = Signal()
    on_alt1 = Signal()

    def __init__(self, manager: "X11GameManager", **kwargs):
        super().__init__(**kwargs)
        self.manager = manager
        self.display = manager.display
        self.logger = logging.getLogger(__name__ + "." + self.__class__.__name__)

        self.handlers = {
            ge.GenericEventCode: self.dispatch_ge,
            X.PropertyNotify: self.on_property_change,
        }
        self.ge_handlers = {xinput.KeyRelease: self.on_key_release}
        self.active_win_id = self.manager.get_active_window()

        self._NET_ACTIVE_WINDOW = self.display.get_atom("_NET_ACTIVE_WINDOW")

    @Slot()
    def run(self):
        root = self.display.screen().root
        root.change_attributes(event_mask=X.PropertyChangeMask)

        while True:
            evt = self.display.next_event()
            if evt.send_event != 0:
                continue

            try:
                handler = self.handlers.get(evt.type)
                if handler:
                    handler(evt)
            except:
                self.logger.error("Error handling event %s", repr(evt), exc_info=True)
                continue

    def dispatch_ge(self, evt: ge.GenericEvent):
        handler = self.ge_handlers.get(evt.evtype)
        if handler:
            handler(evt)

    def on_key_release(self, evt):
        # alt1
        if evt.data.mods.effective_mods & X.Mod1Mask and evt.data.detail == 10:
            self.on_alt1.emit()

    def on_property_change(self, evt: event.PropertyNotify):
        if evt.atom == self._NET_ACTIVE_WINDOW:
            active_win_id = self.manager.get_active_window()

            if self.active_win_id == active_win_id:
                return

            self.active_win_id = active_win_id
            self.on_active_changed.emit()


class X11GameManager(GameManager):
    display: Display

    _instance: Dict[int, GameInstance]

    def __init__(self, **kwargs):
        super().__init__(*kwargs)
        self.display = Display()
        self._NET_ACTIVE_WINDOW = self.display.get_atom("_NET_ACTIVE_WINDOW")
        self._instance = {}

        self.event_thread = QThread()

        self.event_worker = X11EventWorker(self)
        self.event_worker.moveToThread(self.event_thread)
        self.event_thread.started.connect(self.event_worker.run)
        self.event_worker.on_active_changed.connect(self.on_active_window_changed)

        self.event_thread.start()

    def get_instances(self) -> List[GameInstance]:
        out = []

        def visit(window):
            try:
                wm_class = window.get_wm_class()
            except:
                return

            if wm_class and wm_class[0] == "RuneScape":
                if window.id not in self._instance:
                    self.prepare_window(window)
                    self._instance[window.id] = X11GameInstance(
                        self, window, parent=self
                    )
                out.append(self._instance[window.id])

            for child in window.query_tree().children:
                visit(child)

        visit(self.display.screen().root)

        return out

    def get_active_window(self) -> int:
        resp = self.display.screen().root.get_full_property(
            self._NET_ACTIVE_WINDOW, X.AnyPropertyType
        )
        return resp.value[0]

    def prepare_window(self, window: Window):
        # alt1
        window.xinput_grab_keycode(
            xinput.AllDevices,
            X.CurrentTime,
            10,
            xinput.GrabModeAsync,
            xinput.GrabModeAsync,
            True,
            xinput.KeyReleaseMask,
            (X.Mod1Mask,),
        )

    @Slot()
    def on_active_window_changed(self):
        active_winid = self.get_active_window()
        for id_, instance in self._instance.items():
            instance.activeChanged.emit(active_winid == id_)
