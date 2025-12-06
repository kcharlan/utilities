# Rock Paper Scissors Simulator

A "screen saver" style simulation where Rock, Paper, and Scissors battle for dominance.

## Features
-   **Physics Engine**: Elastic collisions, wall bouncing, and momentum.
-   **Game Logic**: Standard RPS rules (Rock > Scissors > Paper > Rock). Winners convert losers.
-   **Auto-Restart**: Infinite loop mode – the simulation automatically restarts after a winner is declared.
-   **Fair Start**: Guaranteed inclusive distribution (min 15% per type) spawned in balanced quadrants to prevent clustering/early wipes.
-   **Customization**:
    -   **Count**: Adjust population size (2-200).
    -   **Speed**: Real-time speed adjustment.
    -   **Size**: Logarithmic scaling for icons.
    -   **Theme**: Light/Dark/System support.
-   **Advanced Physics**:
    -   **Pass Thru**: Reduce chaos by allowing same-type items to pass through each other (Default: On).
    -   **Saving Throws**: Losers have a chance (0-100%) to "reverse" the outcome and convert the winner instead.
-   **Stats & Tracking**:
    -   **Dynamic Leaderboard**: "Wins" display automatically sorts by win count and breaks ties alphabetically.
    -   **Kill Counters**: Each item displays a counter showing how many opponents it has converted. Note: Counters reset if an item is converted.
    -   **Visual Feedback**:
        -   Items that successfully perform a "Saving Throw" appear with inverted colors.
        -   Counters use high-contrast text pathing for readability.

## Running
Simply open `index.html` in your browser.
```bash
open index.html
```
No build steps or dependencies required.
