"""Wires overlay window, tool window, and physics world together."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Gdk

from .config import Config, load_config
from .overlay import DrawMode, OverlayWindow
from .physics import PhysicsWorld
from .tool_window import ToolWindow


class App:
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)

        screen = Gdk.Screen.get_default()
        width = screen.get_width()
        height = screen.get_height()

        self.physics = PhysicsWorld(self.config, width, height)

        self.overlay = OverlayWindow(self.config, self.physics, self._on_stroke_finished)
        self.tool_window = ToolWindow(
            self.config,
            on_run_pause=self._on_run_pause,
            on_clear=self._on_clear,
            on_draw_fixed_toggled=self._on_draw_fixed_toggled,
            on_draw_free_toggled=self._on_draw_free_toggled,
            on_undo=self._on_undo,
            on_gravity_changed=self._on_gravity_changed,
            on_restore=self._on_restore,
        )
        self.overlay.set_tool_window(self.tool_window)

        self._timer_id: int | None = None

    def run(self) -> None:
        self.overlay.show_all()
        self.tool_window.show_all()

        interval_ms = int(1000 / self.config.fps)
        self._timer_id = GLib.timeout_add(interval_ms, self._tick)

        Gtk.main()

    def _tick(self) -> bool:
        dt = 1.0 / self.config.fps
        self.physics.step(dt)
        if self.physics.running:
            self.overlay.redraw()
        return True

    def _on_stroke_finished(self) -> None:
        # Draw mode is a lock: it stays armed across multiple strokes until
        # the user clicks the active draw button again to disarm it.
        self.overlay.redraw()

    def _on_run_pause(self) -> None:
        will_run = not self.physics.running
        if will_run:
            # Snapshot the scene as it looks right before stepping starts -
            # a fresh Run and a resume-after-Pause both count, Pause itself does not.
            self.physics.take_snapshot()
            self.tool_window.set_restore_enabled(True)
        self.physics.running = will_run
        self.tool_window.set_running_state(self.physics.running)

    def _on_clear(self) -> None:
        self.physics.clear()
        self.overlay.redraw()

    def _on_undo(self) -> None:
        self.physics.undo_last()
        self.overlay.redraw()

    def _on_restore(self) -> None:
        if not self.physics.has_snapshot():
            return
        self.physics.restore_snapshot()
        self.tool_window.set_running_state(False)
        self.overlay.redraw()

    def _on_draw_fixed_toggled(self, active: bool) -> None:
        self.overlay.set_draw_mode(DrawMode.FIXED if active else DrawMode.NONE)

    def _on_draw_free_toggled(self, active: bool) -> None:
        self.overlay.set_draw_mode(DrawMode.FREE if active else DrawMode.NONE)

    def _on_gravity_changed(self, angle_degrees: float) -> None:
        self.physics.set_gravity_angle(angle_degrees)


def main() -> None:
    app = App()
    app.run()
