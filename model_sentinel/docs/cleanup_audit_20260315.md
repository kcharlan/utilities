## Assumptions

- **Language/runtime**: Python 3.14 on macOS, using the current stdlib-only design.
- **Delivery model**: Local CLI utility invoked manually or from a user LaunchAgent, not a packaged `pip` distribution.
- **Notification goal**: A click on the macOS notification should open the generated report directly, not merely foreground a sender app.
- **Secrets model**: Provider credentials continue to arrive through environment variables or a sourced shell bootstrap.
- **Public API**: The `model-sentinel` launcher and current runtime-home config layout are treated as the existing user-facing interface.

## Rules / Standards Applied

### Correctness / Safety

- Notification click behavior should match what the UI promises.
- Error paths should not silently degrade into a materially different UX without visibility.

### Robustness & Resilience

- Scheduled execution should not depend on interactive-shell-only `PATH` state.
- macOS notifier selection should be deterministic and diagnosable.

### Best Practices & Maintainability

- Standalone invocation should not require preserving the source checkout when the runtime model is already centered on `~/.model_sentinel/`.

## Findings

### [Correctness / Safety] Finding #1: Fallback notifications cannot satisfy the "click to open report" behavior

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `model_sentinel/model_sentinel/notifications.py:20-32`
  - `model_sentinel/model_sentinel/notifications.py:35-39`
  - When `terminal-notifier` is unavailable, the code falls back to `osascript` `display notification`, which only shows a notification and appends a path into the body text.
- **Impact**:
  - The displayed notification suggests a report path exists, but clicking the notification cannot reliably open that file.
  - Operators get two materially different behaviors depending on local notifier availability.
- **Recommended Fix**:
  - Treat clickable-open behavior as requiring a dedicated notifier backend.
  - If `terminal-notifier` is absent, either emit an explicitly informational notification or log a warning that click-open is unavailable.
  - Do not rely on AppleScript `display notification` for file-opening semantics.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - When the notifier backend cannot open a target, the notification text clearly says it is informational-only.
  - Add a test that exercises the fallback branch and verifies the user-facing message does not imply clickable open support.

### [Robustness] Finding #2: Clickable notification support is PATH-dependent and fragile under launchd

- **Severity**: High
- **Category**: Robustness & Resilience
- **Evidence**:
  - `model_sentinel/model_sentinel/notifications.py:21-29`
  - `model_sentinel/install_launchd.template.sh:70-74`
  - The notifier backend is discovered with `shutil.which("terminal-notifier")`, but the LaunchAgent runner only sources `launchd.env` and then executes the repo launcher.
- **Impact**:
  - A Homebrew-installed `terminal-notifier` can work in an interactive shell and fail under `launchd` if `/opt/homebrew/bin` is missing from `PATH`.
  - The job silently downgrades to the non-clickable AppleScript path with no operator-visible explanation.
- **Recommended Fix**:
  - Resolve `terminal-notifier` from a configurable absolute path, or validate/log which backend was selected.
  - Document and/or seed a safe default `PATH` for LaunchAgent runs.
  - Add a test around backend selection so launchd-specific regressions are visible.
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Launchd runs log the chosen notifier backend and the resolved executable path.
  - A simulated environment without `terminal-notifier` produces an explicit downgrade message instead of silently changing behavior.

### [Best Practices / Maintainability] Finding #3: The shipped launcher is still repo-bound even though the runtime model is runtime-home-first

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `model_sentinel/model-sentinel:1-6`
  - `model_sentinel/__init__.py:1-6`
  - `model_sentinel/install_launchd.template.sh:73-74`
  - The checked-in launcher imports package code from the checkout, and the launchd runner `cd`s into the project dir before executing that repo-local file.
- **Impact**:
  - Users cannot move to a single installed command without either keeping the checkout or building a separate artifact.
  - The project already centralizes mutable state under `~/.model_sentinel/`, so the remaining repo dependency is mostly packaging friction.
- **Recommended Fix**:
  - Ship or document a build step for a single-file executable archive such as a `.pyz` zipapp, then point manual and launchd entrypoints at that artifact instead of the checkout.
  - Keep secrets bootstrap in `~/.model_sentinel/launchd.env` or a small wrapper script.
- **Effort**: M
- **Risk**: Low
- **Acceptance Criteria**:
  - A generated standalone artifact runs `--help`, `healthcheck`, and `scan` without the source repo present.
  - Launchd and manual invocation can target the installed artifact directly.
