# PRD – Gorilla.BAS Web (Single-File HTML Port)

## 1. Product Summary

**Working title:** Gorilla.BAS Web  
**Format:** Single HTML file (openable locally)  
**Tech stack:**

- HTML5 (layout/structure)

- CSS3 (styling/animations)

- Vanilla JavaScript (ES6+; no frameworks, no build steps)

**Concept:**  
Recreate the classic QBasic Gorilla artillery game as a modern single-page web experience. Two gorillas stand on skyscrapers and take turns throwing exploding bananas with configurable angle and velocity, under gravity and wind. The goal is to hit the opponent’s gorilla. Game supports:

- Local 2-player mode (hot seat).

- Player vs AI, with adjustable AI difficulty.

All logic and visuals exist inside a single `.html` file. No external JS/CSS assets.

---

## 2. Goals & Non-Goals

### 2.1 Goals

1. **Faithful core gameplay**
   
   - Turn-based artillery combat with gravity, wind, and building collision.
   
   - Banana trajectories are deterministic given angle, velocity, gravity, wind.

2. **Single-file portability**
   
   - All HTML, CSS, JS in a single `.html` file.
   
   - No network dependencies; playable fully offline.

3. **Two modes: 2P and vs AI**
   
   - Local 2-player.
   
   - Vs AI with difficulty that controls how quickly the AI “locks in” on you (not omniscient).

4. **Usable, modern-ish UX**
   
   - Sidebar settings.
   
   - HUD for wind, scores, current player.
   
   - “Last shot” crib so players can iterate without remembering numbers.

5. **Decent visuals**
   
   - Attractive sprites for gorillas, banana, and explosions vs just rectangles/circles.

### 2.2 Non-Goals

- Online multiplayer, matchmaking, or remote play.

- Packaging as native/mobile apps or PWAs.

- Pixel-perfect visual clone of original Gorilla.BAS.

- Sophisticated AI beyond “learns over a few shots” behavior.

- Complex achievements, meta-progression, or online leaderboards.

---

## 3. Target Platforms & Constraints

- **Browsers:** Recent Chrome, Firefox, Edge, Safari.

- **Devices:** Desktop/laptop primary. Mobile/tablet should work but not heavily optimized.

- **Offline:** Must work fully offline when opened as a local file.

- **Critical constraint:** Everything (HTML, CSS, JS, sprites) lives in one `.html` file.
  
  - Sprites via embedded SVG, inline `<svg>`, or base64 image data URIs.

---

## 4. Game Design

## 4.1 Core Game Loop

1. On round start:
   
   - Generate skyline (buildings).
   
   - Place two gorillas on different buildings (left and right).
   
   - Set wind for the round.

2. Player whose turn it is:
   
   - Sees last shot for that player as a crib.
   
   - Adjusts angle and velocity (0–180°, speed range).
   
   - Presses “Throw” (or AI decides automatically).

3. Banana flies in a ballistic arc under gravity and wind:
   
   - Can go off-screen and re-enter.
   
   - Can hit buildings, either gorilla, or miss entirely.

4. If a gorilla is hit:
   
   - Round ends immediately.
   
   - Score awarded to appropriate player (including self-kill logic).

5. Start next round with new skyline + wind, scores persist until reset.

---

## 4.2 Game Rules & Parameters

### 4.2.1 Coordinate & World Model

- A logical “world” coordinate system underlies the game area (even if only part is visible).

- The viewport (canvas) shows a subset of this world.

- Buildings and gorillas are located in world space; camera maps that to the canvas.

### 4.2.2 Angles & Velocity

**Angle input:**

- Range: **0°–180°**.
  
  - 0° = horizontal to the right.
  
  - 90° = straight up.
  
  - 180° = horizontal to the left.

- This allows “backwards” shots when wind or geometry requires it.

**Velocity:**

- Range: e.g., **5–100** (tunable).

- Final mapping to pixels/sec is tuned so:
  
  - Shots are visually followable.
  
  - You can realistically reach across the city at plausible velocities.

### 4.2.3 Gravity & Wind

**Gravity:**

- Downward acceleration constant, e.g., `g` in game units/sec², scaled to screen.

- Adjustable via Settings: Low / Normal / High.

**Wind:**

- Modeled as horizontal acceleration `wind` (world units/sec²) applied every frame.

- Wind is random per round, but **bounded**:
  
  - Wind Mode (settings): Off / Low / High.
  
  - Each mode defines `maxWindMagnitude`:
    
    - Off: `0`.
    
    - Low: small value, subtle.
    
    - High: noticeable but **not** “hurricane” level.

- Design constraint:
  
  - Game must remain winnable; wind cannot make one side effectively unable to hit the other.

**High-risk:** If `gravity` and `maxWind` are mis-tuned, you get either trivial arcs or unwinnable conditions. Expect a tuning pass.

### 4.2.4 Trajectory Model

At time `t` (starting from 0), given launch from `(x0, y0)`:

- Convert angle to radians: `θ = angle * π / 180`.

- Define initial velocities:
  
  - `vx0 = v0 * cos(θ)`
  
  - `vy0 = v0 * sin(θ)` (positive upwards in math terms; flip sign consistently with screen coordinates).

Then:

- `x(t) = x0 + vx0 * t + 0.5 * wind * t²`

- `y(t)` uses gravity; exact form depends on chosen axis convention:
  
  - If screen y grows downward:
    
    - `vy_screen0 = -vy0`
    
    - `y(t) = y0 + vy_screen0 * t + 0.5 * gravity * t²`

The game loop will step `t` forward using `requestAnimationFrame`.

### 4.2.5 Banana Lifetime & Off-Screen Behavior

**Key change vs naive version:**

- **Leaving the visible canvas does NOT automatically end the turn.**

Rules:

1. The banana is simulated in world space, regardless of whether it’s currently on-screen.

2. If it leaves the visible canvas (e.g., flies off the top):
   
   - Simulation continues.
   
   - If it later re-enters the visible region (or hits buildings/gorillas in world space), handle collision and explosion normally.

3. Turn ends when:
   
   - Banana hits a gorilla → someone scores.
   
   - Banana hits a building and doesn’t kill a gorilla → miss, switch turn.
   
   - Banana reaches “ground level” (world y below city baseline) **and** its x-position is outside the relevant world range (or about to leave permanently), and will never intersect any building/gorilla:
     
     - Consider it a miss.

4. Implement a hard safety cutoff:
   
   - Max allowed simulation time or frame count, e.g., N seconds or N frames.
   
   - If exceeded without collision, treat as miss to avoid infinite loops.

**High-risk:** Getting early-exit logic wrong so valid arcs (offscreen then back on) are wrongly cut off or extremely long loops continue.

### 4.2.6 Buildings & Skyline

- City is a one-dimensional sequence of buildings with:
  
  - Randomized widths and heights.
  
  - x positions contiguous or with slight gaps.

- Two designated buildings for the gorillas:
  
  - One near the left side of the skyline.
  
  - One near the right.

**Skyline variability:**

- Settings include a **variance** level:
  
  - Low: heights clustered around a mean.
  
  - Normal: moderate variance.
  
  - High: heights **can** vary widely (but randomness, not forced extremes every time).

- Implementation detail:
  
  - Heights drawn from a distribution (e.g., normal or some custom function) with variance parameter.

### 4.2.7 Collision & Explosion

**Buildings:**

- Treated as simple rectangles (or polygons if you later support destructible terrain).

- If banana point enters building volume:
  
  - Explosion triggers at impact point.
  
  - Round only continues if nobody dies (no gorilla intersects explosion area).

**Gorillas:**

- Have rectangular hitboxes aligned with sprite extents.

- Two cases:
  
  - Banana intersects **opponent** gorilla hitbox → shooter scores 1 point.
  
  - Banana intersects **shooter’s own** gorilla hitbox (self-kill) → opponent scores 1 point.

**Explosion:**

- Visual: sprite or expanding ring with fade; purely cosmetic in MVP (no terrain deformation required).

- Explosion timing is short (~0.3–0.7s).

### 4.2.8 Turn Structure & Scoring

**Turns:**

- Alternate between Player 1 and Player 2.

- In Vs AI mode:
  
  - Human = Player 1 by default.
  
  - AI = Player 2 (configurable later if desired).

**Scoring logic:**

- If Player A hits Player B → Player A gets 1 point.

- If Player A hits Player A (self-kill) → Player B gets 1 point.

- On any gorilla death:
  
  - Round ends.
  
  - Display small round-end summary.
  
  - Start next round when user clicks “New Round” or similar.

**Score persistence:**

- Scores persist across rounds until user chooses “Reset Scores”.

- Storing in memory only is fine (optionally `localStorage` to persist across refresh).

---

## 4.3 Difficulty & Settings

All settings are accessible via a **sidebar** (slide-in panel or always-visible side column on desktop).

### 4.3.1 Game Mode

- `Local 2-Player`

- `Vs AI`

Switching modes should reset the current round; scores can either reset or be preserved depending on UX choice (specify in UI copy).

### 4.3.2 AI Difficulty

AI is *required*, not optional stretch.

Difficulty levels:

- **Easy**
  
  - Very approximate aiming.
  
  - Large random noise on angle/velocity.
  
  - Adjustments from previous shots are coarse and imperfect.

- **Medium**
  
  - Uses feedback from previous shot (over/under/left/right) to refine aim.
  
  - Moderate noise so it’s beatable but not dumb.

- **Hard**
  
  - More systematic adjustment:
    
    - Basic “search” behavior: uses last shot error to narrow angle/velocity.
  
  - Small but non-zero noise to avoid robotic perfect shots.
  
  - **Constraint:** Hard should typically converge in **2–3 shots**, never by design on the first shot. A true one-shot hit should only be due to random chance, not guaranteed behavior.

AI behavior model (conceptual):

- AI knows:
  
  - Rough target position (enemy gorilla).
  
  - Wind, gravity, and its own building height.
  
  - Its past shots: angle, velocity, and where the banana landed.

- AI logic:
  
  - First shot = exploratory guess (no prior info).
  
  - Subsequent shots adjust based on deviation:
    
    - If shot overshot horizontally, lower velocity or angle; if undershot, raise.
    
    - Optionally separate vertical error vs horizontal error to tune.
  
  - Difficulty modifies:
    
    - Step size of corrections.
    
    - Random jitter levels.
    
    - Whether it fully trusts last error or partially.

**High-risk:** If noise and adjustment steps are mis-tuned, Hard AI becomes either trivial or absurdly accurate. Expect iteration.

### 4.3.3 Physics & Skyline Settings

From sidebar:

- **Gravity:** Low / Normal / High.

- **Wind Mode:** Off / Low / High (each with specific `maxWindMagnitude`).

- **Skyline Variance:** Low / Normal / High.

Direct input fields are not necessary; pre-defined options are enough.

### 4.3.4 Input & “Last Shot” Crib

For each player:

- Angle/velocity inputs show **current** values, but:
  
  - At the start of the player’s turn, they are pre-filled with **that player’s last used angle/velocity**.

- UI shows “Last shot: 63° @ 45” (example) near the inputs.

This applies to both human players and can also display AI’s last shot values (optionally visible for debugging/playtesting).

---

## 5. UX / UI Requirements

### 5.1 Layout

**Top HUD:**

- Game title.

- Wind indicator: arrow + numeric value.

- Scoreboard: “P1: X – P2: Y”.

- Current player indicator: color-coded label, e.g., “Player 1’s Turn”.

**Main Game Area (center):**

- Canvas or absolutely-positioned `<div>` game area with:
  
  - Sky background.
  
  - Buildings & gorillas.
  
  - Banana and explosion effects.

**Bottom Control Panel:**

- Angle input:
  
  - Numeric input (0–180).
  
  - Optional slider.

- Velocity input:
  
  - Numeric input (5–100).
  
  - Optional slider.

- “Throw” button.

- “New Round” / “Restart Round” button.

- “Reset Scores” button.

- Last-shot crib text:
  
  - “Last shot (P1): 63° @ 45” (updated per player).

**Sidebar Panel:**

- Mode: Local 2P / Vs AI.

- AI difficulty: Easy/Medium/Hard.

- Gravity: Low/Normal/High.

- Wind: Off/Low/High.

- Skyline variance: Low/Normal/High.

- Mute/unmute sounds (if sounds implemented).

- Help / About section (controls and rules).

Sidebar can be a slide-out on small screens.

### 5.2 Input & Accessibility

- All UI controls keyboard-accessible:
  
  - Tab order, `Enter` to activate buttons.
  
  - Shortcut keys:
    
    - `Enter` to throw (when controls focused).
    
    - `R` to restart round.

- Use `<button>`, `<label>`, proper ARIA roles for modals/sidebars.

- Provide textual description for:
  
  - Wind.
  
  - Current player.
  
  - Any non-obvious controls.

### 5.3 Visual Style & Sprites

- **Gorillas:**
  
  - Attractive sprites (pixel-art or clean vector).
  
  - Recognizable gorilla silhouette (doesn’t need animation beyond maybe a simple throw pose).

- **Banana:**
  
  - Clear banana sprite (curved yellow shape or simple icon).

- **Explosion:**
  
  - Stylized 2D sprite or simple layered circles; should feel satisfying.

- **Buildings:**
  
  - Mostly geometric, but with minimal detail:
    
    - Windows, slight palette variation, maybe a gradient or subtle outline.

Implementation constraints:

- Sprites implemented via:
  
  - Inline SVG.
  
  - Data-URI PNGs in CSS or `<img>`.
  
  - Or vector shapes drawn on canvas.

- No external asset loading.

---

## 6. Functional Requirements

### 6.1 Must-Haves

1. **Single-file app**
   
   - All HTML, CSS, JS, and sprites in one `.html` file.

2. **Two game modes**
   
   - Local 2-player.
   
   - Vs AI (with difficulty selection).

3. **Angle & velocity inputs**
   
   - Angles 0–180°; velocities in configured range.
   
   - Validation: clamp out-of-range inputs; reject non-numeric gracefully.

4. **Last-shot crib**
   
   - Per player:
     
     - Last angle and velocity stored in state.
     
     - Shown in UI.
     
     - Pre-fill current turn’s inputs.

5. **Random skyline generation**
   
   - Building widths/heights randomized according to variance setting.
   
   - Two buildings chosen as gorilla platforms.

6. **Wind system**
   
   - Per-round random wind within bound from selected mode.
   
   - Wind displayed in HUD.

7. **Physics-based banana motion**
   
   - `requestAnimationFrame` loop.
   
   - Gravity + wind included.
   
   - Off-screen exit allowed; simulation in world space.

8. **Collision & explosion**
   
   - Buildings and gorillas have AABB hitboxes.
   
   - Explosion displayed on impact.
   
   - Hit vs miss logic applied as per scoring rules.

9. **Self-kill handling**
   
   - Self-hit awards point to opponent.

10. **Round & score management**
    
    - Round ends on any gorilla death.
    
    - Scores updated appropriately and displayed.
    
    - “New Round” regenerates skyline & wind.
    
    - “Reset Scores” clears scores and optionally restarts.

11. **Settings sidebar**
    
    - Mode selection, AI difficulty, gravity, wind, skyline variance, basic settings.

### 6.2 Nice-to-Haves

- Sound effects (throw, banana whoosh, explosion; with mute toggle).

- Very light destructible buildings (simple shape adjustments).

- Local best-of-N match mode (first to 5 points).

- Saving last used settings to `localStorage`.

---

## 7. Technical Design

### 7.1 Structure (Within Single HTML File)

**HTML:**

- `<head>`:
  
  - Title, meta, `<style>` block.

- `<body>`:
  
  - HUD (top).
  
  - Main game area (`<canvas>` recommended).
  
  - Bottom control bar.
  
  - Sidebar (static or slide-out).

- `<script>` at end:
  
  - Main game logic.

**JS Modules (logical, not separate files):**

- `GameState`:
  
  - Current player, scores, settings.
  
  - Building list, gorilla positions, wind, gravity.

- `CityGenerator`:
  
  - Generate buildings based on variance setting.

- `Physics`:
  
  - Step function for banana trajectory.
  
  - Collision checks.
  
  - Off-screen / termination logic.

- `Renderer`:
  
  - Draw buildings, gorillas, banana, explosions.

- `AIController`:
  
  - Decision logic for AI angles/velocities.

- `UIController`:
  
  - DOM wiring for controls, sidebar, HUD, and last-shot crib.

- `Loop`:
  
  - `requestAnimationFrame` driver.

No external libraries.

### 7.2 Performance Considerations

- Single canvas draw per frame.

- Avoid layout thrashing; UI updates only on state changes, not every frame.

- Banana simulation capped with max frames/time per shot to prevent infinite loops.

### 7.3 State Management

Core structures:

- `settings`:
  
  - `mode` (2P vs AI).
  
  - `aiDifficulty`.
  
  - `gravityLevel`.
  
  - `windMode`.
  
  - `skylineVariance`.

- `gameState`:
  
  - `currentPlayer` (1 or 2).
  
  - `scores` { p1, p2 }.
  
  - `wind`, `gravity`.
  
  - `buildings[]`.
  
  - `gorillas[]` positions.
  
  - `roundActive`.

- `shotState`:
  
  - `angle`, `velocity`.
  
  - `bananaPosition`, `bananaVelocity`.
  
  - `inFlight`.

- `lastShot`:
  
  - `p1: { angle, velocity }`.
  
  - `p2: { angle, velocity }`.

---

## 8. Non-Functional Requirements

- **Reliability:**
  
  - Inputs robust to bad data; game shouldn’t crash.
  
  - Always recoverable via restart controls.

- **Maintainability:**
  
  - Clear function boundaries for physics, AI, rendering.
  
  - Inline comments where logic is tricky (off-screen handling, AI tuning).

- **Accessibility:**
  
  - Keyboard navigation.
  
  - Descriptive labels, ARIA roles for sidebar and modals.
  
  - Wind and current player text, not just color-coded.

---

## 9. QA & Testing

### 9.1 Core Gameplay Tests

- Two gorillas spawn correctly on opposite sides.

- Wind indicated correctly in HUD and affects trajectory.

- Gravity setting noticeably changes arc shape.

- Angles near 0, 90, 180 produce expected behavior.

- Banana can leave top of screen, re-enter, and still hit buildings/gorillas.

- Self-kill:
  
  - Throwing nearly straight up can kill the shooter.
  
  - Opponent receives point.

- AI:
  
  - Easy misses often and converges slowly.
  
  - Hard converges typically in 2–3 shots, with visible probing first shot.
  
  - No deliberate first-turn perfect shot.

### 9.2 Edge Cases

- Extreme angles + high wind do not create infinite simulations.

- High skyline variance doesn’t place gorillas in unreachable positions (with bounded wind).

- Resizing window while in-flight doesn’t explode everything; worst case, view reflows but game still functions.

- Resetting scores and rounds doesn’t corrupt state.

**Critical/high-risk zones to watch:**

- Physics scaling (gravity, wind, velocity → screen pixels).

- Off-screen banana logic and termination.

- AI difficulty tuning (not too dumb, not too perfect).

---


