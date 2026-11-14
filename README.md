# DrawPhysics

Transparent desktop physics drawing overlay for X11/Linux. Draw freehand shapes
directly on your desktop; they become physics bodies that fall, collide, and
roll under gravity.

## Requirements

- X11 session (Wayland is not supported)
- A compositing window manager for true transparency (KWin, GNOME Shell/Mutter,
  and `picom` all work; the app detects and warns if compositing is off)
- Python 3 with PyGObject (GTK3) available as a system package

## Setup

```bash
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install pymunk pyyaml scipy numpy
```

(`pyyaml`, PyGObject, `scipy`, and `numpy` are commonly already present as
system packages; `--system-site-packages` lets the venv see them.)

## Run

```bash
./.venv/bin/python main.py
```

This opens a full-screen transparent overlay plus a small "DrawPhysics
Controls" window. With no draw button armed, clicks pass through the overlay
to your desktop as normal.

## Controls

- **Run/Pause** — start or freeze the simulation in place.
- **Clear** — remove all drawn shapes.
- **Draw a fixed object (blue)** — locks drawing mode to static obstacles; draw
  as many shapes as you like while it's active, click it again to unlock.
- **Draw a free object (red)** — locks drawing mode to dynamic bodies that fall
  under gravity once Run is pressed; click it again to unlock.
- **Undo** — remove the most recently drawn shape.
- **Gravity direction** — pick a direction from `config.yaml`'s
  `gravity_options`; takes effect immediately.

Draw an open line for a segment-chain body, or draw back close to your
starting point for a filled polygon body.

## Configuration

All colors, line width, restitution, friction, gravity strength/options, and
window sizing live in [config.yaml](config.yaml). Edit and relaunch to change
behavior — nothing is hardcoded in the app.
