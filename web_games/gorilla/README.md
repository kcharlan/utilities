# Gorilla.BAS Reimagined

A modern, web-based artillery game inspired by the classic QBasic **Gorilla.BAS**. While the core concept of two gorillas throwing explosive bananas across a skyline remains, this project is a complete reimagining rather than a direct port. It features a fluid physics engine, particle effects, simultaneous turn-taking, and arcade progression—all contained within a single HTML file.

## Quick Start
- Open `index.html` directly in a modern browser, or serve the folder (e.g., `python3 -m http.server`) and visit `http://localhost:8000`.
- **No dependencies:** Everything is self-contained. No build steps, external assets, or network calls required.

## Key Features
- **Three Game Modes:**
  - **Classic:** Standard 1v1 infinite play (Vs AI or Local PvP).
  - **Arcade:** Survival mode where Player 1 starts with 5 lives.
  - **Demo:** AI vs AI auto-play.
- **Fair Start System:** Ensures playable starting positions by preventing skyline generation that blocks initial shots or creates impossible angles for either player.
- **Counterfire System:** Optional simultaneous turn mode where players lock in shots and fire a volley together.
- **Modern Physics:** High-fidelity trajectory simulation allowing for high-arcing off-screen shots, wind effects, and particle explosions.
- **Procedural Audio & Graphics:** All visuals and sound effects are generated programmatically—no static assets.

## How to Play
- **Goal:** Hit the opposing gorilla with your banana.
- **Controls:**
  - Adjust **Angle** (0–180°) and **Velocity** (5–100).
  - Press **Throw** (or `Enter`).
  - **R** key restarts the round.
- **Strategy:** Account for **Wind** (indicated in the HUD) and **Gravity**.
- **Arcade Mode:** You have limited lives. Survive as long as you can against the AI.

## Demo Mode
- Append `?demo` or `#demo` to the URL (e.g., `index.html?demo`) to launch directly into AI vs AI auto-play.
- Great for screensavers or watching the AI battle it out.
- Interrupt at any time by hitting the Escape key, or by changing the game mode in the sidebar between rounds.

## Settings & Customization
- **Opponent:** Toggle between AI and Local 2-Player.
- **Difficulty:** Adjust AI precision (Easy, Medium, Hard).
- **Physics:** Tweak Gravity and Wind strength.
- **Environment:** Control Skyline Variance (building height differences).
- **Counterfire:** Enable/Disable simultaneous turns.

## Developer Notes
- **Single-File Architecture:** The entire game engine, UI, and assets exist within `index.html`.
- **Tech Stack:** Vanilla JavaScript (ES6+), HTML5 Canvas, CSS3.
- **State Management:** Centralized state for physics and game logic; reactive UI updates.

## Fair-Start Generation Notes
- Generation now uses a strict **validated-or-known-good** contract:
  - A new round is accepted only if `validateLevel(...)` passes.
  - If randomized generation fails, the engine reuses the most recent validated layout.
  - If no known-good layout exists yet, it uses a deterministic emergency layout that is validated once before use.
- Validation is now run with the same round context:
  - Round gravity is threaded into validation checks.
  - Wind samples are derived from the active wind mode (`off`, `low`, `high`).
  - Robustness and clearance checks use the same wind/gravity assumptions as the shot under test.
  - Validation collision priority now matches runtime collision priority (target/gorilla hit is evaluated before building hit).
- To avoid false rejections, validation searches for a **robust hittable shot**, not just the first hittable solution.
- Mid-blocker behavior is intentionally stronger to prevent trivial flat-speed duels, while still bounded in simple fallback mode.
- Gorilla placement includes neighbor-height caps to reduce boxed-in starts caused by immediate tall adjacent buildings.

### Key Tuning Constants (in `index.html`)
- `MID_OBSTACLE_EXTRA`
  - Base amount added above the taller gorilla-side building when forming the center blocker in normal generation.
  - Higher values increase required arc/precision and reduce low-angle straight-line kills.
  - If raised too far, validation/fallback frequency can increase.
- `MID_OBSTACLE_MIN`
  - Minimum allowed center-blocker height in normal generation.
  - Prevents weak middle obstacles on otherwise flatter skylines.
  - Raise this if too many easy “flat and fast” duel rounds still appear.

- `SIMPLE_MID_OBSTACLE_EXTRA`
  - Same concept as `MID_OBSTACLE_EXTRA`, but only for simple fallback generation.
  - Keeps fallback rounds from becoming completely flat/easy while still trying to preserve playability.
- `SIMPLE_MID_OBSTACLE_MIN`
  - Floor height for the middle blocker in simple fallback rounds.
  - Useful to avoid trivial fallback maps with nearly no central structure.
- `SIMPLE_MID_OBSTACLE_MAX`
  - Ceiling for middle blocker height in simple fallback rounds.
  - This cap is important: it prevents fallback rounds from becoming over-sealed and failing validation too often.

- `GORILLA_NEIGHBOR_CAP`
  - Maximum allowed height for buildings immediately adjacent to each gorilla building, relative to gorilla rooftop height.
  - Lower values reduce “boxed-in” starts where first-shot options are overly constrained.
  - Set too low and gorilla neighborhoods can feel too open/repetitive.
- `GORILLA_SECOND_NEIGHBOR_CAP`
  - Same as above, but for the second building away from each gorilla.
  - Acts as a softer buffer ring to keep nearby clusters from becoming extreme.
  - Usually kept somewhat looser than `GORILLA_NEIGHBOR_CAP` to retain skyline character.

### Practical Tuning Workflow
- Change one constant at a time.
- Regenerate at least 20 rounds across wind/gravity modes.
- Watch for three failure modes:
  - Too easy: repeated low-angle direct kills.
  - Too hard: frequent fallback reuse or highly constrained openings.
  - Too flat near gorillas: reduced tactical variety at spawn roofs.
