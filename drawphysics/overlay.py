"""Transparent, click-through, always-on-top full-screen overlay window."""
from __future__ import annotations

import math
from enum import Enum
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from .config import Config, _hex_to_rgba
from .physics import ObjectType, PhysicsWorld, SceneObject
from .stroke import (
    Point,
    bounding_extent,
    fit_lines_to_curve,
    is_closed_loop,
    min_distance_filter,
    smooth_stroke,
)


class DrawMode(Enum):
    NONE = "none"
    FIXED = "fixed"
    FREE = "free"


class OverlayWindow(Gtk.Window):
    def __init__(self, config: Config, physics: PhysicsWorld, on_stroke_finished: Callable[[], None]):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config = config
        self.physics = physics
        self.on_stroke_finished = on_stroke_finished
        # The overlay is an override_redirect window, which X11 stacks above every
        # normal (WM-managed) window regardless of set_keep_above - including the
        # tool window. So while armed and capturing full-screen input, we must
        # explicitly carve the tool window's rectangle out of the input region,
        # or its buttons become unclickable. Set via set_tool_window() once both
        # windows exist.
        self.tool_window: Gtk.Window | None = None

        self.draw_mode = DrawMode.NONE
        self.current_stroke: list[Point] = []
        self.is_drawing = False

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)

        screen = Gdk.Screen.get_default()
        self.screen_width = screen.get_width()
        self.screen_height = screen.get_height()
        self.set_default_size(self.screen_width, self.screen_height)
        self.move(0, 0)

        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)
        else:
            print(
                "WARNING: No compositing window manager detected. "
                "True per-pixel transparency will not work; the overlay "
                "background may render as opaque black. Start a compositor "
                "(e.g. 'picom &') and relaunch for the intended effect."
            )

        self.connect("draw", self._on_draw)
        self.connect("realize", self._on_realize)
        self.connect("map-event", self._on_map_event)
        self.connect("screen-changed", self._on_screen_changed)

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("button-press-event", self._on_button_press)
        self.connect("button-release-event", self._on_button_release)
        self.connect("motion-notify-event", self._on_motion)

    def _on_realize(self, widget):
        gdk_window = self.get_window()
        gdk_window.set_override_redirect(True)
        self._update_input_shape()

    def _on_map_event(self, widget, event):
        # X11 can reset the input shape when the window is mapped, so
        # re-apply it here in addition to at realize time.
        GLib.idle_add(self._update_input_shape)
        return False

    def _on_screen_changed(self, widget, old_screen):
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

    def set_tool_window(self, tool_window: Gtk.Window) -> None:
        self.tool_window = tool_window
        tool_window.connect("configure-event", lambda *_: self._update_input_shape() or False)

    def _tool_window_rect(self) -> cairo.RectangleInt | None:
        if self.tool_window is None or not self.tool_window.get_visible():
            return None
        gdk_win = self.tool_window.get_window()
        if gdk_win is None:
            return None
        # get_origin() returns the CLIENT area's screen position, matching what
        # get_allocated_width/height measure. get_root_origin() returns the
        # outer decorated FRAME's position instead (window-manager titlebar
        # included), which is offset from the client area - using it here
        # made the excluded "hole" land in the wrong place, so clicks near
        # the top of the tool window were still swallowed by the overlay.
        _, x, y = gdk_win.get_origin()
        width = self.tool_window.get_allocated_width()
        height = self.tool_window.get_allocated_height()
        if width <= 0 or height <= 0:
            return None
        return cairo.RectangleInt(x, y, width, height)

    def _update_input_shape(self) -> None:
        """When not armed for drawing, make the whole window click-through by
        setting an empty input shape region. When armed, capture the full
        screen EXCEPT the tool window's rectangle, so its buttons stay
        clickable even while a draw mode is locked/armed."""
        gdk_window = self.get_window()
        if gdk_window is None:
            return
        if self.draw_mode == DrawMode.NONE:
            region = cairo.Region()
        else:
            full_rect = cairo.RectangleInt(0, 0, self.screen_width, self.screen_height)
            region = cairo.Region(full_rect)
            tool_rect = self._tool_window_rect()
            if tool_rect is not None:
                region.subtract(cairo.Region(tool_rect))
        gdk_window.input_shape_combine_region(region, 0, 0)

    def set_draw_mode(self, mode: DrawMode) -> None:
        self.draw_mode = mode
        self.is_drawing = False
        self.current_stroke = []
        self._update_input_shape()
        self.queue_draw()

    def _on_button_press(self, widget, event):
        if self.draw_mode == DrawMode.NONE:
            return False
        if event.button != 1:
            return False
        self.is_drawing = True
        self.current_stroke = [(event.x, event.y)]
        return True

    def _on_motion(self, widget, event):
        if not self.is_drawing:
            return False
        last = self.current_stroke[-1] if self.current_stroke else None
        if last is None or math.hypot(event.x - last[0], event.y - last[1]) >= 1.0:
            self.current_stroke.append((event.x, event.y))
            self.queue_draw()
        return True

    def _on_button_release(self, widget, event):
        if not self.is_drawing:
            return False
        self.is_drawing = False
        self.current_stroke.append((event.x, event.y))

        self._finalize_stroke()

        # draw_mode is left as-is: it now stays armed across multiple strokes
        # (a "lock" toggle) until the tool window's button is clicked again,
        # which calls set_draw_mode(NONE) and updates the input shape itself.
        self.current_stroke = []
        self.queue_draw()

        self.on_stroke_finished()
        return True

    def _finalize_stroke(self) -> None:
        raw_points = self.current_stroke

        # Stage 0: thin out near-duplicate points captured during the drag.
        filtered = min_distance_filter(raw_points, self.config.min_point_distance)
        if len(filtered) < 2:
            return

        closed = is_closed_loop(filtered, self.config.closed_loop_threshold)

        # Stage 1: fit a smooth curve through the raw points (simplify_tolerance
        # bounds how far the curve may wander from the hand-drawn path). This is
        # what keeps a hand-drawn circle round instead of faceted.
        smoothed = smooth_stroke(filtered, closed, self.config.simplify_tolerance)

        # Stage 2: convert that curve into an efficient set of straight segments
        # using a separate, finer tolerance, so the lines still hug the curve.
        final_points = fit_lines_to_curve(smoothed, self.config.line_fit_tolerance)

        if len(final_points) < 2:
            return
        if bounding_extent(final_points) < self.config.min_body_extent:
            return

        # Stage 3: this same point set drives both rendering and the physics body.
        obj_type = ObjectType.FIXED if self.draw_mode == DrawMode.FIXED else ObjectType.FREE
        self.physics.add_stroke(final_points, obj_type)

    def _on_draw(self, widget, ctx: cairo.Context):
        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, self.config.background_alpha)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)

        for obj in self.physics.objects:
            self._draw_object(ctx, obj)

        if self.current_stroke and len(self.current_stroke) >= 2:
            color = (
                self.config.fixed_color_rgba
                if self.draw_mode == DrawMode.FIXED
                else self.config.free_color_rgba
            )
            ctx.set_source_rgba(*color)
            ctx.set_line_width(self.config.line_width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.move_to(*self.current_stroke[0])
            for p in self.current_stroke[1:]:
                ctx.line_to(*p)
            ctx.stroke()

        if self.draw_mode != DrawMode.NONE:
            self._draw_armed_indicator(ctx)

        return False

    def _draw_object(self, ctx: cairo.Context, obj: SceneObject) -> None:
        color = (
            self.config.fixed_color_rgba
            if obj.obj_type == ObjectType.FIXED
            else self.config.free_color_rgba
        )

        points = self.physics.render_points(obj)
        if len(points) < 2:
            return

        if obj.closed:
            ctx.set_source_rgba(color[0], color[1], color[2], 0.35)
            ctx.move_to(*points[0])
            for p in points[1:]:
                ctx.line_to(*p)
            ctx.close_path()
            ctx.fill_preserve()
            ctx.set_source_rgba(*color)
            ctx.set_line_width(self.config.line_width)
            ctx.stroke()
        else:
            ctx.set_source_rgba(*color)
            ctx.set_line_width(self.config.line_width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.move_to(*points[0])
            for p in points[1:]:
                ctx.line_to(*p)
            ctx.stroke()

    def _draw_armed_indicator(self, ctx: cairo.Context) -> None:
        color = (
            self.config.armed_indicator_fixed_hex
            if self.draw_mode == DrawMode.FIXED
            else self.config.armed_indicator_free_hex
        )
        rgba = _hex_to_rgba(color, 0.9)
        ctx.set_source_rgba(*rgba)
        ctx.set_line_width(6)
        margin = 4
        ctx.rectangle(margin, margin, self.screen_width - 2 * margin, self.screen_height - 2 * margin)
        ctx.stroke()

    def redraw(self) -> None:
        self.queue_draw()
