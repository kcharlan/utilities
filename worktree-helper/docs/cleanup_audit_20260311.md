## Assumptions

- **Language**: Python 3.9+ is the supported runtime, so fixes must avoid newer-only syntax.
- **Delivery model**: `worktree` is a single-file CLI/TUI utility with no third-party UI framework.
- **Usage pattern**: Users expect the curses wizard to behave like a nested menu stack, where `Esc` backs out one level at a time and only exits at the top menu.
- **Terminal constraints**: The UI must remain readable on both narrow and very wide terminals without relying on pixel-perfect sizing.
- **Failure handling**: Interactive failures should stay inside the TUI when possible and return the user to a safe prior menu instead of terminating the whole session.

## Rules / Standards

### Correctness / Safety

- Nested cancel behavior must be deterministic and must not drop the user to the shell from intermediate menus.

### Robustness & Resilience

- Empty-list states must degrade gracefully and preserve navigation back to the parent menu.
- Interactive actions launched from the TUI should continue in the TUI until the user explicitly exits.

### Best Practices & Maintainability

- A single sentinel should distinguish "back one level" from "abort the whole session".
- Python 3.9 compatibility must be preserved in type hints and control-flow helpers.

### Readability

- Menu metadata must stay close to the selected item and be readable without scanning across the entire terminal width.

## Findings

### [Correctness] Finding #1: Cancel State Was Conflated With Session Exit

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `/Users/kevinharlan/source/utilities/worktree-helper/worktree:837-905`
  - `/Users/kevinharlan/source/utilities/worktree-helper/worktree:930-979`
  - `/Users/kevinharlan/source/utilities/worktree-helper/worktree:1168-1245`
- **Impact**:
  - Pressing `Esc` in nested flows could terminate the entire TUI session instead of stepping back one menu.
  - Empty-list cases such as `delete` on a repo with no removable worktrees had no recovery path.
- **Recommended Fix**:
  - Separate "back one level" from "exit session" with a dedicated sentinel.
  - Centralize the step-back logic in the wizard controller so repo/action resets happen in one place.
  - This was implemented in the current cleanup pass with `BACK` and explicit reset helpers.
- **Effort**: M
- **Risk**: Medium
- **Acceptance Criteria**:
  - From `delete` -> repo select -> empty worktree list, `Esc` returns to repo selection, then the top action menu, then exits only from the top menu.
  - `create`, `move`, `repair`, and `prune` confirmation flows no longer dump to the shell on intermediate cancels.

### [Readability] Finding #2: Menu Metadata Layout Became Unreadable On Wide Terminals

- **Severity**: Medium
- **Category**: Readability
- **Evidence**:
  - `/Users/kevinharlan/source/utilities/worktree-helper/worktree:613-678`
- **Impact**:
  - Item descriptions were pushed to the far right edge on wide terminals and truncated in practice.
  - Selected rows combined highlight and dim styling, lowering contrast at exactly the point the user needed to read.
- **Recommended Fix**:
  - Render each item as a stacked label + metadata block instead of a split far-left/far-right row.
  - Remove dim styling from active selection metadata.
  - This was implemented in the current cleanup pass with a two-line menu layout and non-dimmed selected metadata.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Menu descriptions remain readable on very wide terminals.
  - Selected items are readable without relying on dimmed text over a highlight background.

### [Robustness] Finding #3: TUI Actions Fell Through To Shell Output

- **Severity**: Medium
- **Category**: Robustness & Resilience
- **Evidence**:
  - `/Users/kevinharlan/source/utilities/worktree-helper/worktree:1667-1694`
  - `/Users/kevinharlan/source/utilities/worktree-helper/worktree:1797-1841`
- **Impact**:
  - Choosing read-only actions such as `list` from the wizard dropped the user out of curses into shell output.
  - This broke the mental model of "I am still inside the tool" and made back-navigation impossible after viewing results.
- **Recommended Fix**:
  - Keep TUI-launched actions inside a session loop.
  - Render action results in a curses message view, then return to the top-level action menu.
  - This was implemented in the current cleanup pass with a session-mode loop and `show_result_tui(...)`.
- **Effort**: M
- **Risk**: Medium
- **Acceptance Criteria**:
  - `list`, `status`, `doctor`, and other TUI-launched actions show their results inside the TUI.
  - After dismissing the result view, the top action menu is shown again without returning to the shell.
