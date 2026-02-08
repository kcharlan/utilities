# Multibody Gravity Lab - User Guide

This guide is for people using the simulator (not maintaining code). It starts with a quickstart and reference, then goes deep on both modes.

## Quickstart

From repo root:

```bash
cd web_games/multibody_sim
open index.html
```

In the app:

1. Pick a mode (`Screensaver` or `User setup`).
2. Use `Start/Pause` to run or stop simulation time.
3. Use `Reset` to regenerate (screensaver) or restore your saved setup (user mode).
4. Tune `Time speed` and `Time multiplier` for simulation rate.
5. Use `Trails` and `Leads` for visual history/forecast.

Quick first run:

1. Leave mode on `Screensaver`.
2. Set `Screensaver bodies` to `3` or `5`.
3. Set `Time multiplier` to `8`.
4. Watch interactions; it will auto-restart at end of cycle.

---

## Quick Reference

## Main Controls

| Control | Available In | What It Does |
|---|---|---|
| `Start/Pause` | Both | Starts or pauses simulation time |
| `Reset` | Both | Screensaver: new random system. User setup: restore baseline setup |
| `Time speed` | Both | Multiplies simulation time rate (slider) |
| `Time multiplier` | Both | Additional simulation time multiplier (number input) |
| `Gravity (G)` | Both | Strength of attraction |
| `Softening (epsilon)` | Both | Reduces extreme close-range acceleration |
| `Trails` + `Trail length` | Both | Past-path rendering |
| `Leads` + `Leads length` | Both | Predicted future path rendering |
| `Screensaver bodies` | Screensaver | Number of generated bodies |
| `Clear` | User setup | Wipe current setup completely |
| `Auto velocities now` | User setup | Auto-assign velocities to current bodies |
| `Load` | User setup | Load setup from JSON file |
| `Save` | User setup | Save setup to JSON file |

## Mouse + Keyboard Shortcuts (User setup mode)

These actions work only in `User setup` while paused unless noted.

| Action | Input |
|---|---|
| Create a body | Left click empty canvas |
| Select body | Left click body |
| Move body | Left drag body |
| Set velocity | Middle-button drag on body |
| Resize mass | Right drag on body |
| Change mass quickly | Mouse wheel over body |
| Delete selected body | `Delete` or `Backspace` |

Notes:

- Velocity arrows start at the body edge (not center).
- If your cursor is inside the body while setting velocity, velocity can resolve to zero.
- Delete key does not remove a body while your cursor focus is inside a text/number input.

---

## Mode Deep Dive: Screensaver

`Screensaver` auto-generates systems and runs continuously.

What to expect:

- Bodies spawn with random mass/position/color.
- Velocities are auto-generated (with special low-body logic for 3-4 body cases to improve interaction likelihood).
- Camera auto-tracks bodies.
- Simulation restarts automatically at cycle end.

End/restart behavior:

1. If one body remains, simulator waits 2 seconds of real time, then resets.
2. Otherwise, restart requires all three gates:
   - quiet timer elapsed,
   - near-pair lock is off,
   - zoom boundary condition is reached.

Useful tuning for viewing:

- Increase `Time multiplier` for faster evolution.
- Lower `epsilon` for stronger close-pass deflection/capture.
- Increase `Screensaver bodies` for more chaotic behavior.
- Turn on `Trails` and `Leads` to see trajectory history and forecast.

---

## Mode Deep Dive: User Setup

`User setup` is for manual scene creation, editing, and repeatable experiments.

## Typical Workflow

1. Switch mode to `User setup`.
2. Place bodies by left-clicking canvas.
3. Set mass and velocity per selected body.
4. Press `Start` to run.
5. Press `Reset` to return to your saved baseline.
6. Use `Save` to export scene to JSON; `Load` to import.

## Building and Editing Bodies

Create/select/move:

- Left click empty space: create new body (default mass).
- Left click body: select it.
- Left drag selected body: reposition it.

Mass controls:

- `Mass` slider in panel for selected body.
- Right-drag on a body to resize mass continuously.
- Mouse wheel over a body for fast adjustments.

Velocity controls:

- Drag velocity with middle-drag.
- Fine-tune with panel fields:
  - `Velocity X`
  - `Velocity Y`
- Press `Enter` in a velocity field to commit and leave edit focus.

Delete controls:

- `Delete selected` button in panel.
- `Delete`/`Backspace` keyboard shortcut.

## Run, Reset, and Clear (Important Differences)

- `Start`: begins simulation.
- `Reset`: restores your baseline setup snapshot (positions, velocities, bodies, colors, etc.).
- `Clear`: removes everything from the board and clears baseline.

When baseline is captured:

- Baseline is captured on `Start`.
- Baseline is also restored/created during `Load`.

## Auto Velocity Features (User mode)

- `Auto-assign velocities on Start`:
  - If enabled, pressing `Start` computes velocities before run.
- `Auto velocity factor`:
  - Scales auto-generated speed.
- `Auto velocities now` button:
  - Applies velocity assignment immediately to current bodies.

## Camera Behavior in User Mode

- While running, camera auto-follows bodies.
- In paused user mode, `Auto camera while paused` controls whether camera reframes while you edit.
- `Reset` also snaps camera to include bodies and velocity arrows with padding.

## Save and Load (JSON)

`Save` writes a JSON file containing:

- bodies (position, velocity, mass, color, ids),
- baseline reset snapshot,
- selected body id,
- sidebar settings (time controls, physics settings, trails/leads settings, user mode toggles).

`Load` restores that JSON into user mode and updates camera/UI accordingly.

Save behavior:

- Browser may show a save dialog (File System Access API).
- If not available, file is downloaded automatically using a generated filename.

## Good Practices for Better Results

- Start with 2-5 bodies when hand-tuning.
- Use lower speeds than expected; high speed often escapes interaction.
- Reduce `epsilon` for stronger close encounters.
- Use `Leads` when tuning velocities; use `Trails` to understand what happened.
- Save setups you like before experimenting further.

## Troubleshooting

- "Delete key does nothing":
  - click on canvas/body first; ensure focus is not inside an input field.
- "Velocity drag seems weak or weird":
  - start drag outside the body edge; use panel velocity fields for precise edits.
- "Reset says no saved setup yet":
  - press `Start` once (captures baseline), or load a saved JSON.
