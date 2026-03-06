# RouterView Setup Guide

This guide walks through everything needed to get RouterView receiving live data from OpenRouter. There are three pieces: RouterView itself, a tunnel to expose it to the internet, and OpenRouter's Broadcast configuration.

---

## Prerequisites

- macOS (the instructions below assume Homebrew; adapt for Linux if needed)
- An OpenRouter account with API usage (so there's data to receive)
- A terminal

---

## Step 1: Install RouterView

```zsh
cd /path/to/utilities/routerview
chmod +x routerview
./routerview
```

On first run, RouterView will:
1. Create a Python venv at `~/.routerview_venv` and install dependencies (takes ~30 seconds the first time).
2. Create the `~/.routerview/` directory and initialize the SQLite database.
3. Start serving at `http://127.0.0.1:8100` (or the next available port).

Leave this running. You should see:

```
RouterView running at http://127.0.0.1:8100
```

Open that URL in a browser to confirm the dashboard loads (it'll be empty -- no data yet).

---

## Step 2: Set Up a Tunnel

RouterView runs on your local machine, but OpenRouter needs to reach it over the public internet to push trace data. A tunnel solves this.

### Option A: Cloudflare Quick Tunnel (easiest, no account needed)

This is the fastest path. No Cloudflare account, no DNS, no configuration. One command.

**Install cloudflared:**

```zsh
brew install cloudflared
```

**Start the tunnel:**

```zsh
cloudflared tunnel --url http://localhost:8100
```

After a few seconds, cloudflared prints a line like:

```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://example-words-here.trycloudflare.com                                              |
+--------------------------------------------------------------------------------------------+
```

Copy that URL. Your RouterView OTLP endpoint is now reachable at:

```
https://example-words-here.trycloudflare.com/v1/traces
```

**Important caveats with Quick Tunnels:**
- The URL **changes every time** you restart cloudflared. You'll need to update the OpenRouter webhook config each time.
- The tunnel only works while the `cloudflared` process is running.
- Rate limited to 200 concurrent requests (more than enough for analytics traces).
- Meant for development/testing, but perfectly fine for personal use.

**Tip**: Run it in a tmux/screen session or a separate terminal tab so it stays up.

### Option B: Cloudflare Named Tunnel (stable URL, free, requires account)

If you want a permanent URL that survives restarts, set up a named tunnel. This requires a free Cloudflare account.

**1. Create a Cloudflare account** at [dash.cloudflare.com](https://dash.cloudflare.com) (free).

**2. Authenticate cloudflared:**

```zsh
cloudflared tunnel login
```

This opens a browser. Pick any domain on your Cloudflare account (you need at least one domain added, even a free one). This creates a credentials file at `~/.cloudflared/cert.pem`.

**3. Create a named tunnel:**

```zsh
cloudflared tunnel create routerview
```

This creates a tunnel with a fixed UUID. Note the UUID printed.

**4. Configure DNS** (so you get a nice subdomain):

```zsh
cloudflared tunnel route dns routerview routerview.yourdomain.com
```

Replace `yourdomain.com` with your actual domain on Cloudflare.

**5. Create a config file** at `~/.cloudflared/config.yml`:

```yaml
tunnel: <YOUR-TUNNEL-UUID>
credentials-file: /Users/<you>/.cloudflared/<UUID>.json

ingress:
  - hostname: routerview.yourdomain.com
    service: http://localhost:8100
  - service: http_status:404
```

**6. Run the tunnel:**

```zsh
cloudflared tunnel run routerview
```

Your permanent endpoint is now:

```
https://routerview.yourdomain.com/v1/traces
```

**7. (Optional) Run as a macOS service** so it starts on boot:

```zsh
sudo cloudflared service install
sudo launchctl start com.cloudflare.cloudflared
```

### Option C: ngrok (alternative, no Cloudflare needed)

```zsh
brew install ngrok
ngrok http 8100
```

Same idea as Cloudflare Quick Tunnel. URL changes on restart with the free tier. ngrok has a paid tier for stable URLs if you prefer it over Cloudflare.

---

## Step 3: Configure OpenRouter Broadcast

Now tell OpenRouter to send trace data to your tunnel URL.

**1. Go to OpenRouter Settings**

Navigate to [openrouter.ai/settings](https://openrouter.ai/settings) and log in.

**2. Find the Broadcast section**

Scroll down to **Observability** (or it may be labeled **Broadcast**). You'll see a list of destination connectors (Arize AI, Braintrust, Datadog, Langfuse, etc.).

**3. Enable Broadcast**

Toggle the **Enable Broadcast** switch to ON.

**4. Add Webhook destination**

Find **Webhook** in the destination list and click **Add Destination**.

**5. Enter your endpoint URL**

In the URL field, enter your tunnel URL with the `/v1/traces` path:

```
https://example-words-here.trycloudflare.com/v1/traces
```

(Or your named tunnel URL like `https://routerview.yourdomain.com/v1/traces`)

If OpenRouter asks for custom headers, you can leave them empty for now. RouterView doesn't require auth on the OTLP endpoint by default.

**6. Test the connection**

Click **Test Connection**. OpenRouter sends a probe request with an `X-Test-Connection: true` header.

If the test passes, the configuration saves. If it fails:
- Confirm RouterView is running (`curl http://localhost:8100/api/health` should return 200).
- Confirm the tunnel is running and the URL is reachable (paste the tunnel URL in a browser -- you should see the RouterView dashboard).
- Check that you included `/v1/traces` at the end of the URL.

**7. Verify with real data**

Make any API request through OpenRouter (from any of your apps, or a quick curl):

```zsh
curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

Within a few seconds, the request should appear in RouterView's log viewer and the KPI cards should update.

---

## Step 4: Verify Schema Mapping (first time only)

OpenRouter's OTLP trace format isn't fully documented, and they could change it at any time. RouterView parses defensively -- unknown fields are captured, missing fields default gracefully -- but on first setup you should verify the mapping is working correctly.

**1. Restart RouterView in debug mode**

Stop RouterView (Ctrl+C) and restart with the `--debug` flag:

```zsh
./routerview --debug
```

This tells RouterView to save every raw OTLP payload it receives to `~/.routerview/traces/`.

**2. Generate a few test requests**

Make 2-3 OpenRouter API requests using different models if possible (so the payloads have variety). Use your apps normally, or run quick curls:

```zsh
# Request 1: a chat completion
curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'

# Request 2: a different model
curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-haiku-4-5-20251001",
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

Wait 10-20 seconds for the traces to arrive.

**3. Check that payloads arrived**

```zsh
ls -la ~/.routerview/traces/
```

You should see JSON files like `2026-03-06T14:32:01_gen-abc123.json`. If the directory is empty, traces aren't reaching RouterView -- go back to Troubleshooting.

**4. Inspect a payload**

```zsh
# Pretty-print the most recent payload
cat ~/.routerview/traces/$(ls -t ~/.routerview/traces/ | head -1) | python3 -m json.tool | less
```

Look for the span attributes. You're checking that the fields RouterView expects are present. The key things to verify:

```
What to look for in the OTLP payload         Maps to DB column
--------------------------------------------  ----------------------------
gen_ai.request.model (or similar)         --> model
gen_ai.usage.prompt_tokens                --> tokens_prompt
gen_ai.usage.completion_tokens            --> tokens_completion
gen_ai.response.finish_reasons            --> finish_reason
Something with "provider"                 --> provider_name
Span startTimeUnixNano / endTimeUnixNano  --> created_at, generation_time_ms
A generation ID (in span name or attrs)   --> id
```

The attribute names may differ from these examples. That's fine -- this is exactly why we're checking.

**5. Verify the dashboard shows correct data**

Open RouterView in your browser and check:
- Do the requests show up in the log viewer?
- Are the model names correct?
- Are token counts populated (not all zeros)?
- Are costs populated?
- Is latency showing a reasonable number?

If something's missing or wrong (e.g., model shows as "unknown" or cost is $0.00), the attribute mapping needs adjustment. The raw payload from step 4 will show you what the actual attribute name is.

**6. If the mapping needs updating**

If OpenRouter uses different attribute names than expected, edit the external mapping file:

```zsh
# Open the mapping file in your editor
open ~/.routerview/attribute_mapping.json
# or: code ~/.routerview/attribute_mapping.json
# or: vim ~/.routerview/attribute_mapping.json
```

This is a JSON file that maps OTLP attribute names to database columns. Each entry looks like:

```json
"tokens_prompt": {
  "attribute": "gen_ai.usage.prompt_tokens",
  "fallbacks": ["gen_ai.usage.input_tokens", "llm.usage.prompt_tokens"],
  "type": "integer",
  "description": "Number of prompt tokens"
}
```

To fix a mapping, find the entry for the column that's wrong (e.g., `tokens_prompt`), and update the `attribute` value to match what you saw in the raw payload from step 4. You can also add the old name to `fallbacks` so both old and new traces continue to parse.

**No restart needed.** RouterView hot-reloads this file on each incoming trace. Save the file, trigger another OpenRouter request, and the new trace will use the updated mapping.

After editing, repeat steps 2-5 to confirm the fix worked.

**7. Switch back to normal mode**

Once everything looks correct, you can restart without `--debug`:

```zsh
./routerview
```

Debug mode captures payloads to disk which consumes space over time (auto-purged after 7 days, but still). Normal mode parses and stores everything the same way, just without writing the raw JSON files.

You only need to do this step once. If OpenRouter changes their schema later, RouterView will still capture all data in `trace_metadata` -- nothing is lost. You'd just re-run this verification process to update the mapping for any new or renamed fields.

---

## Step 5: (Optional) Backfill Historical Data

OpenRouter's Broadcast only sends new data going forward. To import your existing usage history (up to 30 days back), you can use one of two methods:

### API Backfill

RouterView can pull from OpenRouter's Activity API. You'll need a **provisioning API key** (not a regular inference key).

1. In RouterView's Settings page, enter your OpenRouter provisioning API key.
2. Click "Backfill from API" or use the endpoint: `POST http://localhost:8100/api/import/poll`

This imports the last 30 days of daily aggregated data. Note: this is aggregated (daily totals per model), not per-request granularity.

### CSV Import

1. Go to [openrouter.ai/activity](https://openrouter.ai/activity).
2. Use the export feature to download your usage as CSV.
3. In RouterView, go to Settings > Import and upload the CSV file. Or POST it: `POST http://localhost:8100/api/import/csv`

---

## Day-to-Day Operations

### Keeping it running

For RouterView to receive data, both processes need to be running:

1. **RouterView** (`./routerview`)
2. **The tunnel** (`cloudflared tunnel --url http://localhost:8100`)

If either stops, data isn't lost from OpenRouter's side (it just won't be delivered), but you may miss traces during the downtime. The API backfill can recover aggregated data for any gaps within the last 30 days.

### Quick Tunnel URL rotation

If you're using Quick Tunnels, the URL changes every restart. When you restart cloudflared:

1. Copy the new URL from cloudflared's output.
2. Go to OpenRouter Settings > Broadcast > Webhook.
3. Update the URL and re-test the connection.

This is the main annoyance of Quick Tunnels. If it bothers you, switch to a Named Tunnel (Option B above) for a permanent URL.

### Startup script (optional convenience)

You could create a simple script to launch both:

```zsh
#!/bin/zsh
# start_routerview.sh

# Start RouterView in background
/path/to/utilities/routerview/routerview &
ROUTERVIEW_PID=$!

# Wait for it to be ready
sleep 3

# Start tunnel
cloudflared tunnel --url http://localhost:$(cat ~/.routerview/last_port)

# When tunnel is killed (Ctrl+C), also stop RouterView
kill $ROUTERVIEW_PID
```

### Data retention

RouterView keeps all data indefinitely by default. To purge old data, use the Settings page or the API:

```zsh
curl -X POST "http://localhost:8100/api/purge?before=2025-01-01"
```

### Checking health

```zsh
curl http://localhost:8100/api/health
```

---

## Troubleshooting

**"Test Connection failed" in OpenRouter**
- Is RouterView running? Check `curl http://localhost:8100/api/health`
- Is the tunnel running? Try opening the tunnel URL in a browser.
- Did you append `/v1/traces` to the tunnel URL?
- Firewall blocking? The tunnel should bypass this, but check if cloudflared has network permissions on macOS (System Settings > Privacy & Security > Network).

**Tunnel URL not working in browser**
- cloudflared may take 5-10 seconds after startup before the URL is reachable.
- If using a named tunnel, verify DNS propagation: `dig routerview.yourdomain.com`

**Data not appearing in RouterView**
- Run RouterView with `--debug` to capture raw OTLP payloads: `./routerview --debug`
- Check `~/.routerview/traces/` for incoming payload files.
- If payloads arrive but data doesn't appear, there may be a parsing issue -- the attribute mapping may need updating. See Step 4 above for the full inspection and fix workflow.
- If no payloads arrive at all, the issue is tunnel/network, not parsing. Check the tunnel and OpenRouter Broadcast config.

**Data appears but fields are wrong (model "unknown", cost $0.00, etc.)**
- OpenRouter may have changed their OTLP attribute names. Re-run the Step 4 verification process: restart with `--debug`, inspect a raw payload, and update `~/.routerview/attribute_mapping.json` to match. No code editing or restart needed -- the mapping file is hot-reloaded on every trace.

**RouterView won't start (port in use)**
- RouterView auto-increments the port. Check the output for the actual port.
- Or specify a different port: `./routerview -p 8200`

**"cloudflared: command not found"**
- Install it: `brew install cloudflared`
- Or download directly from [GitHub releases](https://github.com/cloudflare/cloudflared/releases)
