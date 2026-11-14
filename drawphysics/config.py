"""YAML configuration loading for DrawPhysics."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b, alpha)


@dataclass
class GravityOption:
    label: str
    angle_degrees: float


@dataclass
class Config:
    fixed_color_hex: str
    free_color_hex: str
    line_width: float
    restitution: float
    friction: float
    gravity_magnitude: float
    gravity_options: list[GravityOption]

    fps: int
    physics_substeps: int

    min_point_distance: float
    simplify_tolerance: float
    line_fit_tolerance: float
    closed_loop_threshold: float
    segment_radius: float
    min_body_extent: float

    tool_window_width: int
    tool_window_height: int
    tool_window_bg_hex: str
    tool_window_title: str

    armed_indicator_fixed_hex: str
    armed_indicator_free_hex: str
    background_alpha: float

    @property
    def fixed_color_rgba(self) -> tuple[float, float, float, float]:
        return _hex_to_rgba(self.fixed_color_hex)

    @property
    def free_color_rgba(self) -> tuple[float, float, float, float]:
        return _hex_to_rgba(self.free_color_hex)

    @property
    def tool_window_bg_rgba(self) -> tuple[float, float, float, float]:
        return _hex_to_rgba(self.tool_window_bg_hex)

    def gravity_vector(self, angle_degrees: float) -> tuple[float, float]:
        """0 deg = straight down, positive = clockwise."""
        import math

        theta = math.radians(angle_degrees)
        gx = self.gravity_magnitude * math.sin(theta)
        gy = self.gravity_magnitude * math.cos(theta)
        return (gx, gy)


def load_config(path: str | None = None) -> Config:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    gravity_options = [
        GravityOption(label=opt["label"], angle_degrees=float(opt["angle_degrees"]))
        for opt in raw.get("gravity_options", [])
    ]
    if not gravity_options:
        gravity_options = [GravityOption(label="Down (standard)", angle_degrees=0)]

    sim = raw.get("simulation", {})
    stroke = raw.get("stroke", {})
    tool_window = raw.get("tool_window", {})
    overlay = raw.get("overlay", {})

    return Config(
        fixed_color_hex=raw["fixed_object"]["color"],
        free_color_hex=raw["free_object"]["color"],
        line_width=float(raw.get("line_width", 4)),
        restitution=float(raw.get("restitution", 0.4)),
        friction=float(raw.get("friction", 0.6)),
        gravity_magnitude=float(raw.get("gravity_magnitude", 900)),
        gravity_options=gravity_options,
        fps=int(sim.get("fps", 60)),
        physics_substeps=int(sim.get("physics_substeps", 1)),
        min_point_distance=float(stroke.get("min_point_distance", 4)),
        simplify_tolerance=float(stroke.get("simplify_tolerance", 2.0)),
        line_fit_tolerance=float(stroke.get("line_fit_tolerance", 0.75)),
        closed_loop_threshold=float(stroke.get("closed_loop_threshold", 18)),
        segment_radius=float(stroke.get("segment_radius", 3.0)),
        min_body_extent=float(stroke.get("min_body_extent", 6)),
        tool_window_width=int(tool_window.get("width", 260)),
        tool_window_height=int(tool_window.get("height", 340)),
        tool_window_bg_hex=tool_window.get("background_color", "#2b2b2b"),
        tool_window_title=tool_window.get("title", "DrawPhysics Controls"),
        armed_indicator_fixed_hex=overlay.get("armed_indicator_color_fixed", raw["fixed_object"]["color"]),
        armed_indicator_free_hex=overlay.get("armed_indicator_color_free", raw["free_object"]["color"]),
        background_alpha=float(overlay.get("background_alpha", 0.0)),
    )
