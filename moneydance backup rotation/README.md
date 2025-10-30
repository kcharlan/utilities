# Moneydance Backup Rotation

## Overview
- `moneydance_rotate_backups.sh` prunes old Moneydance backup exports that live on a mounted NAS share.
- Retention is expressed in days, not file counts, so every export from a retained day is preserved.
- The script resolves the mount point dynamically from the macOS mount table, ensuring it follows the share even if the mount location changes.
- All configurable values live at the top of the script, making it launchd-friendly and easy to tune without editing the main logic.

## Configuration
Edit the variables declared near the top of `moneydance_rotate_backups.sh` to match your environment:

| Variable | Purpose |
| --- | --- |
| `NAS_SERVER` | NAS host name or IP address (e.g., `192.168.1.18`). |
| `NAS_SHARE_NAME` | Share name as it appears in the mount table (e.g., `kevin`). |
| `BACKUP_DIRECTORY_NAME` | Directory on the share that contains Moneydance backups (`Moneydance-Mac-backups` by default). |
| `MAX_DAYS_TO_KEEP` | Maximum number of calendar days to preserve (default `4`). |
| `DRY_RUN` | Set to `1` to log deletions without removing anything (default `1` for safety). |
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

## Install as a Launch Agent
1. **Place the script.** Copy `moneydance_rotate_backups.sh` to an absolute path that the LaunchAgent can reach (for example, `~/Library/Scripts/moneydance_rotate_backups.sh` or `/usr/local/bin/moneydance_rotate_backups.sh`).
2. **Make it executable.**  
   ```bash
   chmod 755 /absolute/path/to/moneydance_rotate_backups.sh
   ```
3. **Test manually (optional).**  
   Leave `DRY_RUN=1`, run the script directly, review the logs (and optionally set `DEBUG_LOG=1` for extra detail). When you are confident in the retention results, switch `DRY_RUN=0` to allow files to be pruned.
4. **Create a LaunchAgent plist.** Save a file such as `~/Library/LaunchAgents/com.example.moneydance.rotate.plist` with contents similar to:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
     <dict>
       <key>Label</key>
       <string>com.example.moneydance.rotate</string>
       <key>ProgramArguments</key>
       <array>
         <string>/bin/zsh</string>
         <string>/absolute/path/to/moneydance_rotate_backups.sh</string>
       </array>
       <key>StartCalendarInterval</key>
       <dict>
         <key>Hour</key>
         <integer>23</integer>
         <key>Minute</key>
         <integer>30</integer>
       </dict>
       <key>StandardOutPath</key>
       <string>/Users/your-user/Library/Logs/moneydance_rotate_backups.out</string>
       <key>StandardErrorPath</key>
       <string>/Users/your-user/Library/Logs/moneydance_rotate_backups.err</string>
       <key>WorkingDirectory</key>
       <string>/</string>
     </dict>
   </plist>
   ```
   Adjust the `Label`, `ProgramArguments`, run schedule, and log paths to match your preferences.
5. **Load the agent.**
   ```bash
   launchctl load -w ~/Library/LaunchAgents/com.example.moneydance.rotate.plist
   ```
6. **Verify.**
   ```bash
   launchctl list | grep moneydance.rotate
   tail -f ~/Library/Logs/moneydance_rotate_backups.out
   ```

To change the schedule later, edit the plist and run:
```bash
launchctl unload ~/Library/LaunchAgents/com.example.moneydance.rotate.plist
launchctl load -w ~/Library/LaunchAgents/com.example.moneydance.rotate.plist
```

## Notes
- The script relies on the share already being mounted; mount automation should be handled separately if required.
- Running it frequently (e.g., hourly) is safe—the retention logic always keeps the most recent `MAX_DAYS_TO_KEEP` days intact.
- Consider pointing `LOG_FILE` to a LaunchAgent-controlled log directory (such as `~/Library/Logs`) to consolidate output with stdout/stderr capture.
