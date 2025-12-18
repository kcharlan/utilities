
# LLM Usage Tracker — Full Installation Guide (macOS)

This guide covers **complete setup from scratch** on a new Mac, assuming the repo folder
`/Users/<username>/llm_collector` contains the collector source code.

---

## 🚨 0. REQUIRED FIRST STEP — Set Your API Key

Before doing *anything else*, you **must define and configure your API key**.  
The key must match between the **collector server** and the **browser extension**, or requests will fail.

### 0.1 Choose Your API Key

Pick a strong random value — for example:
```bash
openssl rand -hex 24
```
Copy that 48-character string somewhere safe.

You’ll need to:
- Set it in the collector (via Docker `API_KEY` environment variable)
- Set it in your browser extension code (background.js or config section)

### 0.2 Update the Collector Configuration

Edit the `docker-compose.yml` (created in step 3) and replace:
```
- API_KEY=CHANGE_ME_TO_A_RANDOM_LONG_VALUE
```
with:
```
- API_KEY=<your_secret_key_here>
```

### 0.3 Update the Browser Extension

Inside your extension’s `background.js`, locate the configuration section (or constant) defining the API key, such as:

```js
const API_KEY = "CHANGE_ME_TO_A_RANDOM_LONG_VALUE";
```

Replace it with your same `<your_secret_key_here>` string.

✅ **Important:** The collector will reject requests if these do not match.

---

## 1. Prerequisites

- **macOS** (tested on Monterey+)
- **Docker Desktop** (for containerized collector)
- **Vivaldi / Chromium-based browser** (for the extension)
- **curl** (preinstalled on macOS)

---

## 2. Folder Layout

Expected repo layout:

```
llm_collector/
├── collector/
│   └── collector.py        ← Flask app exposing /collect, /counters, /reset
├── state.json              ← Created automatically
├── collector.log           ← Log file
├── snapshots/              ← Daily counter snapshots
└── Dockerfile + docker-compose.yml (added below)
```

---

## 3. Build the Collector Container

### 3.1 Create the Dockerfile

Save as `Dockerfile` in `/Users/<username>/llm_collector_container/`:

```dockerfile
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir gunicorn flask
WORKDIR /workspace/llm_collector
EXPOSE 9000
CMD ["/bin/sh", "-lc", "\
    if [ -f requirements.txt ]; then pip install -r requirements.txt || true; fi; \    mkdir -p snapshots; \    exec gunicorn --chdir /workspace/llm_collector --workers 1 --bind 0.0.0.0:9000 --timeout 120 --access-logfile - --error-logfile - collector.collector:app \  "]
```

### 3.2 Create the Docker Compose File

Save as `docker-compose.yml` in the same folder:

```yaml
version: "3.9"
services:
  llm-collector:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: llm-collector
    ports:
      - "9000:9000"
    environment:
      - API_KEY=<your_secret_key_here>
    volumes:
      - /Users/<username>/llm_collector:/workspace/llm_collector:rw
    working_dir: /workspace/llm_collector
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:9000/counters || exit 1"]
      interval: 10s
      timeout: 3s
      retries: 10
      start_period: 5s
    restart: unless-stopped
```

### 3.3 Build and Run

```bash
cd /Users/<username>/llm_collector_container
docker compose up --build -d
```

Test it:
```bash
curl -H "X-API-KEY: <your_secret_key_here>" http://127.0.0.1:9000/counters
```

You should get JSON counters.

---

## 4. Install the Browser Extension

### 4.1 Folder Layout

Example:
```
llm_usage_extension/
├── manifest.json
├── background.js
├── popup.html
└── popup.js
```

### 4.2 Load the Extension

1. Open `vivaldi://extensions` (or Chrome → Extensions → Manage Extensions)
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select your `llm_usage_extension/` folder
5. Reload the extension

### 4.3 Verify It Works

- Open Perplexity / ChatGPT / Gemini / ChatLLM / T3 Chat in browser
- Send a prompt
- Click the extension icon → counts should appear
- Check collector logs via:
  ```bash
  tail -f /Users/<username>/llm_collector/collector.log
  ```

---

## 5. Automatic Daily Reset (macOS launchd)

### 5.1 Create Reset Script

`/Users/<username>/llm_collector/reset_collector.sh`

```bash
#!/bin/bash
API_KEY="<your_secret_key_here>"
curl -s -X POST -H "X-API-KEY: $API_KEY" http://127.0.0.1:9000/reset >> /Users/<username>/llm_collector/collector.log 2>&1
```

Make it executable:
```bash
chmod +x /Users/<username>/llm_collector/reset_collector.sh
```

### 5.2 Create LaunchAgent

Save as `~/Library/LaunchAgents/com.llmcollector.reset.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.llmcollector.reset</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>0</integer></dict>
  <key>ProgramArguments</key>
  <array><string>/Users/<username>/llm_collector/reset_collector.sh</string></array>
  <key>StandardOutPath</key><string>/Users/<username>/llm_collector/reset_launchd.log</string>
  <key>StandardErrorPath</key><string>/Users/<username>/llm_collector/reset_launchd.err</string>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.llmcollector.reset.plist
```

Check:
```bash
launchctl list | grep llmcollector
```

Logs go to:
```
~/llm_collector/reset_launchd.log
~/llm_collector/reset_launchd.err
```

---

## 6. Daily Operation

- Keep Docker running (collector stays active)
- Use browser as normal — extension logs AI endpoint usage
- At midnight, counters reset automatically
- Use `/snapshots` folder for daily saved state

---

## 7. Troubleshooting

| Problem | Fix |
|----------|------|
| No counters increment | Check extension’s popup debug lines and console log |
| Server not reachable | Confirm Docker container is running: `docker ps` |
| Repeated counts rising on idle | Ensure using delta-push background.js version |
| launchd job not firing | `launchctl unload/load` again and check log paths |

---

**End of Installation Guide**
