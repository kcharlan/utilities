# Gorilla.BAS Web

Modern browser remake of the classic QBasic **Gorilla.BAS** artillery game. Two gorillas toss explosive bananas across a skyline, accounting for gravity and wind. Play solo versus the built-in AI or locally with a friend.

## Quick Start
- Open `index.html` directly in a modern browser, or serve the folder (e.g., `python -m http.server` from this directory) and visit `http://localhost:8000`.
- Everything is self-contained—no build, no external assets or network calls required.

## How to Play
- Goal: hit the opposing gorilla with your banana before they hit you.
- Enter an **angle** (0–180°) and **velocity** (5–100), then press **Throw**.
- Bananas keep simulating off-screen and can arc back into view.
- Round ends when a gorilla is hit; scores increment for the scorer and a new skyline is generated after a short countdown.
- Keyboard: **R** restarts the round. **Enter** throws when focused on inputs.

## Controls & Settings
- **Mode:** Vs AI or Local 2-Player. In AI mode, Player 1 is human, Player 2 is AI.
- **AI Difficulty:** Easy, Medium, Hard (affects how quickly your AI opponent dials you in for the kill).
- **Gravity:** Low/Normal/High.
- **Wind:** Off/Low/High (wind is randomized each round within the selected bound).
- **Skyline Variance:** Low/Normal/High for building heights.
- **Mute Sounds:** Toggle all audio.
- **Reset Scores:** Regenerate skyline.
- **Reset Scores:** Clear the scoreboard.

## Gameplay & Physics Notes
- World units: `velocityScale` maps player velocity to world units/sec; physics updates at a fixed 15 ms tick with capped frame-time accumulation.
- Early-miss detection ends hopeless shots sooner (e.g., when wind will keep carrying the banana past the target).
- Bananas spin in flight at a rate tied to launch speed (clamped to a sensible range) and are slightly oversized for viewability.
- Explosion visuals and timings are unified across hits and misses; a larger boom triggers on gorilla hits.

## AI Overview
- The AI samples angles/velocities to find a viable trajectory with current wind and gravity (`computeOptimalShot`) to hit the opposing player.
- Difficulty controls a queue of intentional misses; offsets shrink toward the solved shot. Hard may miss 0–2 times, Medium 0–5, Easy 3–10+.
- AI waits briefly before throwing to keep pacing natural and rebuilds its plan when rounds regenerate.

## Graphics & Sound
- Canvas-based rendering (no external textures). Gorillas are drawn programmatically with shaded fur, face detail, and player-color accents; the banana is a curved, speckled, gradient sprite.
- Audio is synthesized with Web Audio: filtered-noise whoosh for throws, layered explosions (tight for misses/buildings, deeper with a sub-boom for gorilla hits). Mute toggle lives in the sidebar.

## Developer Notes
- Single-file implementation in `index.html` (HTML/CSS/JS). No build tooling; edit and refresh.
- State is centralized in the `state` object; settings live in `settings`. Core subsystems: skyline generation, gorilla placement with mid-obstacle enforcement, physics stepper, AI planner, renderer, and audio synthesis.
- Responsive layout: HUD is sticky; sidebar collapses behind a toggle on narrower widths.

