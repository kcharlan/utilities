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
- Interrupt at any time by hitting the Esscape key, or by changing the game mode in the sidebar between rounds.

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
