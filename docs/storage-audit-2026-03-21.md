# Storage Audit - 2026-03-21

## Scope

Manual disk-usage triage on Kevin's macOS system to explain why the internal SSD was reporting roughly 44-46% consumption despite that level feeling unexpectedly high.

No cleanup actions were performed during this pass. This document records what was checked, what was found, and which checks should become first-class probes in an automated utility.

## High-Level Conclusion

The reported storage use is real, but a large fraction is not normal live file data.

- APFS container used: `473.1 GB`
- Data volume reported by APFS: `443.4 GB`
- Data volume visible via `du`: about `223 GB`
- Inferred hidden/system-managed delta on Data volume: about `220 GB`

That hidden delta aligns closely with local APFS/Time Machine snapshot overhead and other system-managed/purgeable storage. In other words, the machine is not actually carrying `~443 GB` of ordinary live files on the writable volume.

## Top-Level Accounting

### APFS / volume view

- `/` (`Macintosh HD` system snapshot): `12.5 GB`
- `/System/Volumes/Data`: `443.4 GB` consumed per APFS metadata
- `Preboot`: `15.7 GB`
- `Recovery`: `1.3 GB`
- `VM`: negligible
- APFS container total in use: `473.1 GB`

### Visible live files on Data volume

`du -xhd 1 /System/Volumes/Data` found about `223 GB` of reachable live data:

- `Users`: `145 GB`
- `Applications`: `50 GB`
- `private`: `7.5 GB`
- `System`: `7.3 GB`
- `opt`: `7.0 GB`
- `Library`: `5.5 GB`

The gap between `223 GB` visible and `443.4 GB` consumed on Data is the main explanation for the "unexpected" disk usage.

## Snapshot Findings

`tmutil listlocalsnapshots /` returned 18 local snapshots:

- `com.apple.TimeMachine.2026-03-12-183727.local`
- `com.apple.TimeMachine.2026-03-18-190026.local`
- Hourly snapshots across `2026-03-20`
- Four snapshots on `2026-03-21`

`diskutil apfs listSnapshots /System/Volumes/Data` marked them `Purgeable: Yes`.

`tmutil destinationinfo` showed a configured Time Machine destination:

- Name: `Samsung970-2TB`
- Kind: `Local`

`tmutil latestbackup` returned nothing during this pass.

### Interpretation

Inference: local snapshots are a major contributor to the `~220 GB` hidden delta. This is not proven down to the byte by `tmutil`, but it is the cleanest explanation that fits the accounting.

## Home Directory Findings

`/System/Volumes/Data/Users/kevinharlan`: `145 GB`

Largest top-level items:

- `Library`: `73 GB`
- `Downloads`: `11 GB`
- `source`: `8.2 GB`
- `.lmstudio`: `19 GB`
- `.cache`: `5.0 GB`
- `Pictures`: `4.4 GB`
- `.ollama`: `4.1 GB`
- `Documents`: `3.5 GB`
- `.vscode`: `2.9 GB`
- `.npm`: `2.4 GB`
- `.claude`: `2.3 GB`

## Largest Live-Data Buckets

### User Library

`~/Library`: `73 GB`

Largest subdirectories:

- `Application Support`: `39 GB`
- `Caches`: `14 GB`
- `Containers`: `8.5 GB`
- `Group Containers`: `6.0 GB`
- `Photos`: `2.6 GB`
- `WebKit`: `933 MB`
- `Developer`: `852 MB`

### Application Support

Largest items:

- `Evernote`: `13 GB`
- `Claude`: `12 GB`
- `com.docker.install`: `2.4 GB`
- `Code`: `2.2 GB`
- `Google`: `1.9 GB`
- `Vivaldi`: `1.0 GB`
- `Samsung`: `934 MB`
- `OperaGX`: `742 MB`
- `Comet`: `721 MB`
- `discord`: `633 MB`
- `eM Client`: `611 MB`

Important detail:

- `Evernote/resource-cache`: `10 GB`
- `Claude/vm_bundles`: `10 GB`
- `com.docker.install/in_progress/Docker.app`: `2.4 GB`

### Caches

`~/Library/Caches`: `14 GB`

Largest items:

- `Homebrew`: `3.2 GB`
- `Comet`: `2.0 GB`
- `ms-playwright`: `1.5 GB`
- `Vivaldi`: `1.0 GB`
- `com.openai.atlas`: `972 MB`
- `Yarn`: `726 MB`
- `com.apple.textunderstandingd`: `601 MB`
- `evernote-client-updater`: `533 MB`
- `SiriTTS`: `483 MB`
- `pip`: `451 MB`
- `node-gyp`: `379 MB`
- `t3-code-desktop-updater`: `296 MB`
- `com.openai.chat`: `247 MB`

Safe/high-confidence reclaim candidates from this set:

- `Homebrew/downloads`: `3.1 GB`
- `ms-playwright`: `1.5 GB`
- `pip`: `451 MB`
- `Yarn`: `726 MB`
- browser/app caches when the corresponding apps are closed

### Containers

`~/Library/Containers`: `8.5 GB`

Largest items:

- `com.docker.docker`: `2.9 GB`
- `com.microsoft.teams2`: `1.2 GB`
- `com.microsoft.Excel`: `1.0 GB`
- `com.microsoft.Word`: `877 MB`
- `com.apple.mediaanalysisd`: `466 MB`
- `com.infinitekind.MoneydanceOSX`: `300 MB`
- `com.microsoft.Powerpoint`: `275 MB`

Important nuance:

- `Docker.raw` reports `32 GB` logical size but only `2.9 GB` allocated on disk.
- The future utility must distinguish logical size from allocated blocks for sparse files.

### Group Containers

`~/Library/Group Containers`: `6.0 GB`

Largest items:

- `UBF8T346G9.ms`: `5.3 GB`
- `UBF8T346G9.Office`: `365 MB`
- `UBF8T346G9.com.microsoft.teams`: `170 MB`

Inside `UBF8T346G9.ms`:

- `AI`: `2.8 GB`
- `Library/Caches`: `2.5 GB`
- notable temp/download artifact: `CFNetworkDownload_WGyBLx.tmp` about `2.0 GB`
- notable model artifact: `AI/L/1.model` about `2.3 GB`

This looks like a mix of Microsoft AI/runtime payloads and cached download material.

## Model Stores / Developer Artifacts

### LM Studio

`~/.lmstudio`: `19 GB`

- `models`: `15 GB`
- `extensions`: `2.9 GB`

Model families:

- `mlx-community`: `11 GB`
- `lmstudio-community`: `4.1 GB`

### Ollama

`~/.ollama`: `4.1 GB`

- almost entirely `models/blobs`

### Whisper cache

`~/.cache/whisper`: `4.9 GB`

Contains a `large-v3.pt` file around `2.9 GB`, plus associated cache material.

### VS Code

`~/.vscode`: `2.9 GB`

- almost entirely `extensions`

Largest extension:

- `cqframework.cql-0.7.12`: `416 MB`

Other large extensions include Azure, OpenAI, Claude, Gemini, Java, and Copilot-related packages.

### NPM cache

`~/.npm`: `2.4 GB`

- almost entirely `_cacache`

## Downloads / User Media

`~/Downloads`: `11 GB`

Large files:

- `Kevin Workout 2.mov`: `5.7 GB`
- `Kevin workout 1.mov`: `4.8 GB`

These two files account for almost the entire directory.

## Other Meaningful Findings

- `~/Pictures/Photos Library.photoslibrary`: `4.4 GB`
- `~/Documents/OSCAR_Data`: `2.7 GB`
- `~/apple-health-extract/apple_health_export`: `2.8 GB`
- `~/source`: `8.2 GB`
  - `kevin-CodexBar`: `2.0 GB`
  - `CodexBar`: `1.7 GB`
  - `utilities`: `1.4 GB`
  - `marktext`: `2.1 GB`

These are not necessarily deadweight, but they are real live storage consumers.

## OneDrive / File Provider Nuance

Several OneDrive paths showed multi-GB apparent file sizes, but actual allocated size did not always match:

- `20250621_134531000_iOS.MOV`
  - metadata size about `2.9 GB`
  - allocated size in `CloudStorage`: `0 B`
- `20241125_201852000_iOS.MOV`
  - metadata size about `2.65 GB`
  - allocated size in `CloudStorage`: `2.5 GB`

Conclusion: file-provider placeholders can look enormous if a tool reads metadata size only. The automated utility must capture:

- apparent size
- allocated size
- placeholder/offloaded state when available

## Ranked Cleanup Candidates

### Highest value / likely safe

1. APFS local snapshots: inferred `~220 GB`
2. `~/Library/Caches`: `14 GB`
3. `~/.cache/whisper`: `4.9 GB`
4. `~/.npm/_cacache`: `2.4 GB`
5. `~/Library/Application Support/com.docker.install/in_progress/Docker.app`: `2.4 GB`

### Moderate value / situational

1. `~/Library/Application Support/Evernote/resource-cache`: `10 GB`
2. `~/Library/Application Support/Claude/vm_bundles`: `10 GB`
3. `~/.lmstudio/models`: `15 GB`
4. `~/.ollama/models`: `4.1 GB`
5. `~/.vscode/extensions`: `2.9 GB`

### User-owned files to review manually

1. `~/Downloads/Kevin Workout 2.mov`: `5.7 GB`
2. `~/Downloads/Kevin workout 1.mov`: `4.8 GB`
3. `~/Pictures/Photos Library.photoslibrary`: `4.4 GB`
4. `~/apple-health-extract/apple_health_export`: `2.8 GB`
5. `~/Documents/OSCAR_Data`: `2.7 GB`

## Commands Used

Primary probes used in this audit:

- `df -h /`
- `df -h /System/Volumes/Data`
- `diskutil info /`
- `diskutil info /System/Volumes/Data`
- `diskutil apfs list`
- `diskutil apfs listSnapshots /System/Volumes/Data`
- `tmutil listlocalsnapshots /`
- `tmutil destinationinfo`
- `tmutil latestbackup`
- `du -xhd 1 ...` across:
  - `/System/Volumes/Data`
  - `/System/Volumes/Data/Users/kevinharlan`
  - `~/Library`
  - `~/Library/Application Support`
  - `~/Library/Caches`
  - `~/Library/Containers`
  - `~/Library/Group Containers`
  - `/Applications`
  - `/private/var`
- `find ... -type f -size +2G`
- `stat -f ...`
- `ls -lh`

## Checks To Automate

The future utility should turn each of these into a named backend probe:

- APFS volume/container accounting
- local snapshot inventory and age
- visible vs APFS-reported usage delta
- top-level `du` breakdown for Data volume
- home-directory breakdown
- library-specific deep scans
- sparse-file detection
- cloud placeholder detection
- app cache detection
- stale installer/update residue detection
- model-store inventory
- large file inventory with policy tagging

## Suggested Immediate Next Actions

If doing manual cleanup before the full utility exists:

1. Review and likely thin/delete local Time Machine snapshots.
2. Purge low-risk caches:
   - Homebrew
   - Playwright
   - pip
   - Yarn
   - general browser/app caches
3. Inspect and likely remove `~/Library/Application Support/com.docker.install/in_progress/Docker.app` if Docker is not actively updating.
4. Decide whether `Claude` VM bundles, `LM Studio` models, `Ollama` models, and the two workout videos should remain local.
