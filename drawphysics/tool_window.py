"""Small always-on-top control window with Run/Pause, Clear, Draw, Undo, Gravity dropdown."""
from __future__ import annotations

import math
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf

from .config import Config, _hex_to_rgba


ICON_COLOR = "#111111"


def _symbolic_icon(name: str, pixel_size: int = 18, color: str = ICON_COLOR) -> Gtk.Image:
    """A themed symbolic icon recolored to a flat, fixed color (symbolic icons
    are single-color SVGs that normally inherit the theme's foreground color;
    we override that via a CSS color so every icon matches regardless of theme)."""
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(pixel_size)
    r, g, b, _ = _hex_to_rgba(color)
    rgba = Gdk.RGBA(r, g, b, 1.0)
    image.override_color(Gtk.StateFlags.NORMAL, rgba)
    return image


def _swatch_icon(hex_color: str, size: int = 16) -> Gtk.Image:
    """A small filled square in the given color, used for the draw-mode buttons."""
    r, g, b, a = _hex_to_rgba(hex_color)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(r, g, b, a)
    ctx.rectangle(0, 0, size, size)
    ctx.fill()
    ctx.set_source_rgba(0, 0, 0, 0.35)
    ctx.set_line_width(1)
    ctx.rectangle(0.5, 0.5, size - 1, size - 1)
    ctx.stroke()
    surface.flush()
    return Gtk.Image.new_from_surface(surface)


def _arrow_pixbuf(angle_degrees: float, size: int = 20, color: str = ICON_COLOR) -> GdkPixbuf.Pixbuf:
    """A pixbuf of an arrow pointing in the gravity direction: 0deg = down,
    positive = clockwise, matching the config's angle convention."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    ctx.translate(size / 2, size / 2)
    ctx.rotate(-math.radians(angle_degrees))

    r, g, b, a = _hex_to_rgba(color)
    ctx.set_source_rgba(r, g, b, a)
    ctx.set_line_width(2.0)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    shaft = size * 0.32
    head = size * 0.22

    ctx.move_to(0, -shaft)
    ctx.line_to(0, shaft)
    ctx.stroke()

    ctx.move_to(-head, shaft - head)
    ctx.line_to(0, shaft)
    ctx.line_to(head, shaft - head)
    ctx.stroke()

    surface.flush()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)


def _icon_button(icon: Gtk.Image, tooltip: str, toggle: bool = False) -> Gtk.Button:
    button = Gtk.ToggleButton() if toggle else Gtk.Button()
    button.set_image(icon)
    button.set_always_show_image(True)
    button.set_tooltip_text(tooltip)
    return button


class ToolWindow(Gtk.Window):
    def __init__(
        self,
        config: Config,
        on_run_pause: Callable[[], None],
        on_clear: Callable[[], None],
        on_draw_fixed_toggled: Callable[[bool], None],
        on_draw_free_toggled: Callable[[bool], None],
        on_undo: Callable[[], None],
        on_gravity_changed: Callable[[float], None],
        on_restore: Callable[[], None],
    ):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title=config.tool_window_title)
        self.config = config
        self._on_run_pause = on_run_pause
        self._on_clear = on_clear
        self._on_draw_fixed_toggled = on_draw_fixed_toggled
        self._on_draw_free_toggled = on_draw_free_toggled
        self._on_undo = on_undo
        self._on_gravity_changed = on_gravity_changed
        self._on_restore = on_restore

        self._suppress_toggle_events = False

        self.set_default_size(config.tool_window_width, config.tool_window_height)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_title(config.tool_window_title)

        self._apply_background_color()

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hbox.set_border_width(12)
        self.add(hbox)

        self._run_icon = _symbolic_icon("media-playback-start-symbolic")
        self._pause_icon = _symbolic_icon("media-playback-pause-symbolic")

        self.run_pause_button = _icon_button(self._run_icon, "Run")
        self.run_pause_button.connect("clicked", lambda *_: self._on_run_pause())
        hbox.pack_start(self.run_pause_button, False, False, 0)

        self.clear_button = _icon_button(_symbolic_icon("edit-clear-all-symbolic"), "Clear")
        self.clear_button.connect("clicked", lambda *_: self._on_clear())
        hbox.pack_start(self.clear_button, False, False, 0)

        hbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)

        self.draw_fixed_button = _icon_button(
            _swatch_icon(config.fixed_color_hex), "Draw a fixed object (blue)", toggle=True
        )
        self.draw_fixed_button.connect("toggled", self._on_fixed_toggled)
        hbox.pack_start(self.draw_fixed_button, False, False, 0)

        self.draw_free_button = _icon_button(
            _swatch_icon(config.free_color_hex), "Draw a free object (red)", toggle=True
        )
        self.draw_free_button.connect("toggled", self._on_free_toggled)
        hbox.pack_start(self.draw_free_button, False, False, 0)

        hbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)

        self.undo_button = _icon_button(_symbolic_icon("edit-undo-symbolic"), "Undo")
        self.undo_button.connect("clicked", lambda *_: self._on_undo())
        hbox.pack_start(self.undo_button, False, False, 0)

        self.restore_button = _icon_button(
            _symbolic_icon("document-revert-symbolic"),
            "Restore scene to the last time Run was pressed",
        )
        self.restore_button.connect("clicked", lambda *_: self._on_restore())
        self.restore_button.set_sensitive(False)
        hbox.pack_start(self.restore_button, False, False, 0)

        hbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)

        gravity_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, float)
        for opt in config.gravity_options:
            gravity_store.append([_arrow_pixbuf(opt.angle_degrees), opt.label, opt.angle_degrees])

        self.gravity_combo = Gtk.ComboBox.new_with_model(gravity_store)
        self.gravity_combo.set_tooltip_text("Gravity direction")

        icon_renderer = Gtk.CellRendererPixbuf()
        self.gravity_combo.pack_start(icon_renderer, False)
        self.gravity_combo.add_attribute(icon_renderer, "pixbuf", 0)

        self.gravity_combo.set_active(0)
        self.gravity_combo.connect("changed", self._on_gravity_combo_changed)
        hbox.pack_start(self.gravity_combo, False, False, 0)

        self.connect("destroy", lambda *_: Gtk.main_quit())

    def _apply_background_color(self) -> None:
        r, g, b, a = self.config.tool_window_bg_rgba
        css = f"""
        window {{
            background-color: rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {a});
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _on_fixed_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._suppress_toggle_events:
            return
        active = button.get_active()
        if active:
            self._suppress_toggle_events = True
            self.draw_free_button.set_active(False)
            self._suppress_toggle_events = False
        self._on_draw_fixed_toggled(active)

    def _on_free_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._suppress_toggle_events:
            return
        active = button.get_active()
        if active:
            self._suppress_toggle_events = True
            self.draw_fixed_button.set_active(False)
            self._suppress_toggle_events = False
        self._on_draw_free_toggled(active)

    def _on_gravity_combo_changed(self, combo: Gtk.ComboBox) -> None:
        active_iter = combo.get_active_iter()
        if active_iter is None:
            return
        row = combo.get_model()[active_iter]
        label, angle = row[1], row[2]
        combo.set_tooltip_text(f"Gravity direction: {label}")
        self._on_gravity_changed(angle)

    def set_running_state(self, running: bool) -> None:
        self.run_pause_button.set_image(self._pause_icon if running else self._run_icon)
        self.run_pause_button.set_tooltip_text("Pause" if running else "Run")

    def set_restore_enabled(self, enabled: bool) -> None:
        self.restore_button.set_sensitive(enabled)
