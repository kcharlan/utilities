# Moneydance Backup Rotation

## Overview
- `moneydance_rotate_backups.sh` prunes old Moneydance backup exports that live on a mounted NAS share.
- Retention is expressed in days, not file counts, so every export from a retained day is preserved.
- The script resolves the mount point dynamically from the macOS mount table, ensuring it follows the share even if the mount location changes.
- Logs are emitted to stdout, with optional mirroring to a log file (auto-creating the parent directory) and macOS syslog.
- All configurable values live at the top of the script, making it easy to tune without editing the main logic.

## Configuration
Edit the variables declared near the top of `moneydance_rotate_backups.sh` to match your environment:

| Variable | Purpose |
| --- | --- |
| `NAS_SERVER` | NAS host name or IP address (e.g., `192.168.1.18`). |
| `NAS_SHARE_NAME` | Share name as it appears in the mount table (e.g., `kevin`). |
| `BACKUP_DIRECTORY_NAME` | Directory on the share that contains Moneydance backups (`Moneydance-Mac-backups` by default). |
| `MAX_DAYS_TO_KEEP` | Maximum number of calendar days to preserve (default `4`). |
| `DRY_RUN` | Set to `1` to log deletions without removing anything (default `0`, so enable before dry runs). |
| `LOG_FILE` | Optional absolute path for an additional log file. Leave empty to skip file logging. |
| `USE_SYSLOG` | Set to `1` to mirror log output to the macOS system log via `logger`. |
| `DEBUG_LOG` | Set to `1` for extra diagnostics (lists discovered days, retained files, etc.). |

Every external command path (`/sbin/mount`, `/usr/bin/find`, etc.) is also specified explicitly in case your installation requires overrides.

## How It Works
1. Reads the macOS mount table to locate the mount point for `//NAS_SERVER/NAS_SHARE_NAME`.
2. Combines the mount point with `BACKUP_DIRECTORY_NAME` to find the Moneydance backup directory.
3. Scans all files under that directory and groups them by their modification day (using file metadata, not naming conventions).
4. Retains every file that belongs to the most recent `MAX_DAYS_TO_KEEP` days; older days and their files are marked for removal.
5. Deletes the files marked for pruning (or just reports them when `DRY_RUN=1`).

If the share is not mounted or the backup directory is missing, the script logs a warning and exits without attempting any cleanup.

## Local Usage
1. **Store the script.** Copy `moneydance_rotate_backups.sh` into `~/Library/Scripts`.
2. **Make it executable.**
   ```bash
   chmod 755 ~/Library/Scripts/moneydance_rotate_backups.sh
   ```
3. **Add the directory to your PATH.** Append the following to your shell profile (for example, `~/.zshrc`) and reload your shell:
   ```bash
   export PATH="$HOME/Library/Scripts:$PATH"
   ```
4. **Test manually (optional).**  
   Set `DRY_RUN=1`, run the script directly, review the logs (and optionally set `DEBUG_LOG=1` for extra detail). When you are confident in the retention results, restore `DRY_RUN=0` to allow files to be pruned.

## Notes
- The script relies on the share already being mounted; mount automation should be handled separately if required.
- Running it frequently (e.g., hourly) is safe—the retention logic always keeps the most recent `MAX_DAYS_TO_KEEP` days intact.
- Consider pointing `LOG_FILE` to a persistent log directory (such as `~/Library/Logs`) to keep rotation output alongside other script logs.
- When running under macOS Ventura or later, grant Full Disk Access to the shell binary that launches the script (or run it from a terminal that already has the entitlement) to avoid `Operation not permitted` errors when scanning the NAS.
