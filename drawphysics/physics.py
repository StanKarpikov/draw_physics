"""pymunk world wrapper: body creation from strokes, stepping, gravity, bounds pruning."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pymunk

from .config import Config
from .stroke import Point, centroid, is_closed_loop, polygon_area


class ObjectType(Enum):
    FIXED = "fixed"
    FREE = "free"


@dataclass
class SceneObject:
    obj_type: ObjectType
    body: pymunk.Body
    shapes: list[pymunk.Shape]
    # Local-space points (relative to body position) used for rendering the outline each frame.
    local_points: list[Point]
    closed: bool


class PhysicsWorld:
    def __init__(self, config: Config, window_width: int, window_height: int):
        self.config = config
        self.window_width = window_width
        self.window_height = window_height
        self.space = pymunk.Space()
        self.space.gravity = (0, 0)
        self.running = False
        self.objects: list[SceneObject] = []
        self.set_gravity_angle(0.0)
        # Scene state as of the most recent Run press (resume included, Pause
        # ignored): a list of (obj_type, world-space points) rebuildable via
        # add_stroke, restored verbatim (frozen) by restore_snapshot().
        self._snapshot: list[tuple[ObjectType, list[Point]]] | None = None

    def set_gravity_angle(self, angle_degrees: float) -> None:
        self.space.gravity = self.config.gravity_vector(angle_degrees)

    def _apply_material(self, shape: pymunk.Shape) -> None:
        shape.friction = self.config.friction
        shape.elasticity = self.config.restitution

    def add_stroke(self, points: list[Point], obj_type: ObjectType) -> SceneObject | None:
        if len(points) < 2:
            return None

        closed = is_closed_loop(points, self.config.closed_loop_threshold) and len(points) >= 4

        if obj_type == ObjectType.FIXED:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (0, 0)
        else:
            body = pymunk.Body(body_type=pymunk.Body.DYNAMIC)
            body.position = centroid(points)

        shapes: list[pymunk.Shape] = []

        if closed:
            loop_points = points[:-1] if points[0] == points[-1] else points
            if polygon_area(loop_points) < 0:
                loop_points = loop_points[::-1]
            local_points = [(px - body.position.x, py - body.position.y) for px, py in loop_points]
            try:
                shapes = self._build_convex_decomposition(local_points, body)
            except Exception:
                shapes = []
            if not shapes:
                shapes = self._build_segment_chain(local_points + [local_points[0]], body)
            local_points_render = local_points + [local_points[0]]
        else:
            local_points_render = [(px - body.position.x, py - body.position.y) for px, py in points]
            shapes = self._build_segment_chain(local_points_render, body)

        if not shapes:
            return None

        if obj_type == ObjectType.FREE:
            for shape in shapes:
                shape.density = 1.0
            self.space.add(body)
            for shape in shapes:
                self._apply_material(shape)
                self.space.add(shape)
            body.mass = max(body.mass, 1.0)
        else:
            self.space.add(body)
            for shape in shapes:
                self._apply_material(shape)
                self.space.add(shape)

        scene_obj = SceneObject(
            obj_type=obj_type,
            body=body,
            shapes=shapes,
            local_points=local_points_render,
            closed=closed,
        )
        self.objects.append(scene_obj)
        return scene_obj

    def _build_segment_chain(self, local_points: list[Point], body: pymunk.Body) -> list[pymunk.Shape]:
        shapes = []
        radius = self.config.segment_radius
        for i in range(len(local_points) - 1):
            a = local_points[i]
            b = local_points[i + 1]
            if a == b:
                continue
            seg = pymunk.Segment(body, a, b, radius)
            shapes.append(seg)
        return shapes

    def _build_convex_decomposition(self, local_points: list[Point], body: pymunk.Body) -> list[pymunk.Shape]:
        """Triangulate a simple polygon via ear clipping, producing convex pymunk.Poly shapes."""
        triangles = _ear_clip_triangulate(local_points)
        shapes = []
        for tri in triangles:
            poly = pymunk.Poly(body, tri)
            shapes.append(poly)
        return shapes

    def remove_object(self, obj: SceneObject) -> None:
        for shape in obj.shapes:
            if shape in self.space.shapes:
                self.space.remove(shape)
        if obj.body in self.space.bodies:
            self.space.remove(obj.body)
        if obj in self.objects:
            self.objects.remove(obj)

    def undo_last(self) -> None:
        if self.objects:
            self.remove_object(self.objects[-1])

    def clear(self) -> None:
        for obj in list(self.objects):
            self.remove_object(obj)

    def step(self, dt: float) -> None:
        if not self.running:
            return
        self.space.step(dt)
        self._prune_out_of_bounds()

    def _prune_out_of_bounds(self) -> None:
        margin = 0.0
        to_remove = []
        for obj in self.objects:
            bb = None
            for shape in obj.shapes:
                shape_bb = shape.cache_bb()
                if bb is None:
                    bb = shape_bb
                else:
                    bb = bb.merge(shape_bb)
            if bb is None:
                continue
            fully_outside = (
                bb.right < -margin
                or bb.left > self.window_width + margin
                or bb.bottom < -margin
                or bb.top > self.window_height + margin
            )
            if fully_outside:
                to_remove.append(obj)
        for obj in to_remove:
            self.remove_object(obj)

    def render_points(self, obj: SceneObject) -> list[Point]:
        body = obj.body
        return [body.local_to_world(p) for p in obj.local_points]

    def take_snapshot(self) -> None:
        """Capture the current scene (as world-space points per object) so it
        can be brought back later via restore_snapshot(), even after further
        simulation, undo, clear, or new strokes have changed the scene."""
        self._snapshot = [
            (obj.obj_type, self.render_points(obj)) for obj in self.objects
        ]

    def has_snapshot(self) -> bool:
        return self._snapshot is not None

    def restore_snapshot(self) -> None:
        """Rebuild the scene exactly as it was at the last take_snapshot()
        call, frozen (not running) - discards anything that happened since."""
        if self._snapshot is None:
            return
        self.clear()
        for obj_type, points in self._snapshot:
            self.add_stroke(points, obj_type)
        self.running = False


def _ear_clip_triangulate(points: list[Point]) -> list[list[Point]]:
    """Simple ear-clipping triangulation for a simple (non-self-intersecting) polygon."""
    pts = points[:]
    if len(pts) < 3:
        return []
    if _signed_area(pts) < 0:
        pts = pts[::-1]

    indices = list(range(len(pts)))
    triangles: list[list[Point]] = []
    guard = 0
    max_guard = len(pts) * len(pts) + 10

    while len(indices) > 3 and guard < max_guard:
        guard += 1
        ear_found = False
        n = len(indices)
        for i in range(n):
            i_prev = indices[(i - 1) % n]
            i_curr = indices[i]
            i_next = indices[(i + 1) % n]
            a, b, c = pts[i_prev], pts[i_curr], pts[i_next]
            if not _is_convex(a, b, c):
                continue
            triangle_contains_other = False
            for j in indices:
                if j in (i_prev, i_curr, i_next):
                    continue
                if _point_in_triangle(pts[j], a, b, c):
                    triangle_contains_other = True
                    break
            if triangle_contains_other:
                continue
            triangles.append([a, b, c])
            indices.pop(i)
            ear_found = True
            break
        if not ear_found:
            break

    if len(indices) == 3:
        triangles.append([pts[indices[0]], pts[indices[1]], pts[indices[2]]])
    elif len(indices) > 3:
        # Fallback: fan triangulation for any remaining (possibly degenerate) case.
        for i in range(1, len(indices) - 1):
            triangles.append([pts[indices[0]], pts[indices[i]], pts[indices[i + 1]]])

    return [t for t in triangles if _signed_area(t) != 0]


def _signed_area(pts: list[Point]) -> float:
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _is_convex(a: Point, b: Point, c: Point) -> bool:
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return cross > 0


def _point_in_triangle(p: Point, a: Point, b: Point, c: Point) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign(p, a, b)
    d2 = sign(p, b, c)
    d3 = sign(p, c, a)

    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)

    return not (has_neg and has_pos)
