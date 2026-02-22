#!/usr/bin/env bash
set -euo pipefail

echo "=== T3.chat Credential Extractor (from cURL) ==="
echo ""
echo "Steps to get your cURL command:"
echo "  1. Open https://t3.chat in Chrome and log in"
echo "  2. Open DevTools: press F12 (or Cmd+Option+I on Mac)"
echo "  3. Click the Network tab"
echo "  4. In the filter bar, type:  /api/chat"
echo "  5. Send any message in T3.chat (e.g. type 'hello' and press Enter)"
echo "  6. A 'chat' entry appears in the Network tab"
echo "  7. Right-click the 'chat' entry → Copy → Copy as cURL"
echo ""
echo "Paste your cURL command below, then press Enter and Ctrl+D:"
echo ""

curl_cmd=$(cat)

# Chrome uses -b for cookies, not -H 'Cookie: ...'
# Try -b first (Chrome default), then -H Cookie as fallback
cookies=$(echo "$curl_cmd" | grep -oP "(?<=-b ')[^']*" || \
          echo "$curl_cmd" | grep -oP '(?<=-b ")[^"]*' || \
          echo "$curl_cmd" | grep -oP "(?<=-H 'Cookie: )[^']*" || \
          echo "$curl_cmd" | grep -oP '(?<=-H "Cookie: )[^"]*' || \
          echo "")

if [ -z "$cookies" ]; then
    echo "ERROR: Could not find cookies in cURL command."
    echo "Expected -b '...' or -H 'Cookie: ...' flag."
    echo "Make sure you copied the full cURL command from DevTools."
    exit 1
fi

# convex-session-id is available both as a cookie AND in the JSON body.
# Extract from cookies first (more reliable), fall back to body.
convex_session_id=$(echo "$cookies" | \
    grep -oP '(?<=convex-session-id=)[^;]+' || \
    echo "$curl_cmd" | grep -oP '(?<="convexSessionId":")[^"]*' || \
    echo "")

if [ -z "$convex_session_id" ]; then
    echo "ERROR: Could not find convex-session-id in cookies or body."
    exit 1
fi

# Build and encode credentials
json=$(printf '{"cookies":"%s","convex_session_id":"%s"}' "$cookies" "$convex_session_id")
encoded=$(echo -n "$json" | base64)

echo ""
echo "=== Success! ==="
echo ""
echo "Cookie: ${cookies:0:60}..."
echo "convexSessionId: $convex_session_id"
echo ""
echo "Add this to your shell profile (~/.zshrc or ~/.bashrc):"
echo ""
echo "export T3_CHAT_CREDS='$encoded'"
