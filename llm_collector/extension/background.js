// ===== LLM Usage Counter — Server SOT + Idempotent Adds + Seq Handshake =====

// --- Config ---
const COLLECTOR = "http://127.0.0.1:9000";
const API_KEY   = "<your key here>";
const DEBUG = true;

const DEDUPE_WINDOW_MS = 1500;      // per (tabId, host, path)
const PUSH_COALESCE_MS = 250;       // batch quickly

// Observe these domains; allow/deny rules decide what counts.
const URL_FILTERS = [
  "*://chatgpt.com/*",
  "*://*.chatgpt.com/*",
  "*://chat.openai.com/*",
  "*://api.openai.com/*",
  "*://*.perplexity.ai/*",
  "*://gemini.google.com/*",
  "*://generativelanguage.googleapis.com/*",
  "*://*.googleapis.com/*"
];

// --- Allow rules: endpoints that indicate a user "send" ---
const HOST_ALLOW = {
  "api.openai.com": [
    /^\/v1\/chat\/completions$/,
    /^\/v1\/responses$/,
    /^\/v1\/completions$/
  ],
  "chatgpt.com": [
    /^\/backend-api\/f\/conversation$/,
    /^\/backend-api\/conversation$/
  ],
  "chat.openai.com": [
    /^\/backend-api\/f\/conversation$/,
    /^\/backend-api\/conversation$/
  ],
  "*.chatgpt.com": [
    /^\/backend-api\/f\/conversation$/,
    /^\/backend-api\/conversation$/
  ],
  "*.perplexity.ai": [
    /^\/rest\/sse\/perplexity_ask$/
  ],
  "gemini.google.com": [
    /^\/_\/BardChatUi\/data\/assistant\.lamda\.BardFrontendService\/StreamGenerate$/
  ],
  "generativelanguage.googleapis.com": [
    /:generateContent$/,
    /:streamGenerateContent$/
  ],
  "*.googleapis.com": [
    /:generateContent$/,
    /:streamGenerateContent$/
  ]
};

// --- Deny rules: noisy endpoints to ignore ---
const HOST_DENY = {
  "chatgpt.com": [
    /^\/ces\//,
    /^\/backend-api\/aip\/connectors\//,
    /^\/backend-api\/conversation\/experimental\/generate_autocompletions$/,
    /^\/backend-api\/f\/conversation\/prepare$/,
    /^\/backend-api\/lat\/r$/,
    /^\/backend-api\/sentinel\//,
    /^\/backend-api\/unified_user_signals$/,
    /^\/cdn-cgi\/challenge-platform\//
  ],
  "chat.openai.com": [
    /^\/ces\//,
    /^\/backend-api\/aip\/connectors\//,
    /^\/backend-api\/conversation\/experimental\/generate_autocompletions$/,
    /^\/backend-api\/f\/conversation\/prepare$/,
    /^\/backend-api\/lat\/r$/,
    /^\/backend-api\/sentinel\//,
    /^\/backend-api\/unified_user_signals$/,
    /^\/cdn-cgi\/challenge-platform\//
  ],
  "ab.chatgpt.com": [ /^\/v1\/rgstr$/ ],
  "realtime.chatgpt.com": [ /^\/v1\/vp\/status$/, /^\/v1\/vps$/ ],
  "*.perplexity.ai": [
    /^\/rest\/event\/analytics$/,
    /^\/rest\/entry\//,
    /^\/rest\/thread\/mark_viewed\//,
    /^\/rest\/autosuggest\/list-autosuggest$/,
    /^\/cdn-cgi\/challenge-platform\//
  ],
  "gemini.google.com": [
    /^\/_\/BardChatUi\/data\/batchexecute$/
  ]
};

// --- Host pattern helpers ---
function matchHostPattern(host, pattern) {
  if (!pattern.includes("*")) return host === pattern;
  const suffix = pattern.replace(/^\*\./, "");
  return host === suffix || host.endsWith("." + suffix);
}
function rulesForHost(table, host) {
  if (table[host]) return table[host];
  for (const [pat, rules] of Object.entries(table)) {
    if (pat.startsWith("*.") && matchHostPattern(host, pat)) return rules;
  }
  return null;
}
function allowedByHost(u) {
  const allow = rulesForHost(HOST_ALLOW, u.hostname);
  if (!allow) return false;
  const pathq = u.pathname + (u.search || "");
  return allow.some(rx => rx.test(u.pathname) || rx.test(pathq));
}
function deniedByHost(u) {
  const deny = rulesForHost(HOST_DENY, u.hostname);
  if (!deny) return false;
  const pathq = u.pathname + (u.search || "");
  return deny.some(rx => rx.test(u.pathname) || rx.test(pathq));
}

// --- Debounce (avoid burst double counts) ---
const recent = new Map();
function dedupeKey(details, u) { return `${details.tabId}|${u.hostname}|${u.pathname}`; }
function passesDebounce(details, u) {
  const now = Date.now();
  const k = dedupeKey(details, u);
  const last = recent.get(k) || 0;
  if (now - last < DEDUPE_WINDOW_MS) return false;
  recent.set(k, now);
  return true;
}

// --- Storage keys ---
const CLIENT_ID_KEY = "llm_client_id_v1"; // stable per browser profile
const SEQ_KEY       = "llm_seq_v1";       // last successfully applied seq (server agrees)
const PENDING_KEY   = "llm_pending_v1";   // {host: count} unsent or unacked

// --- Debug buffer for popup ---
const DEBUG_BUF_MAX = 200;
const debugBuf = [];
function dbgPush(decision, d, u, reason) {
  const rec = {
    ts: Date.now(),
    decision,
    method: d.method,
    type: d.type || null,
    host: u.hostname,
    path: u.pathname,
    tabId: d.tabId ?? null,
    reason: reason || null
  };
  debugBuf.push(rec);
  if (debugBuf.length > DEBUG_BUF_MAX) debugBuf.splice(0, debugBuf.length - DEBUG_BUF_MAX);
  if (DEBUG) console.log("[LLM-UC]", rec);
}

// --- chrome.storage helpers ---
function getStore(keys) { return new Promise(r => chrome.storage.local.get(keys, v => r(v || {}))); }
function setStore(obj)  { return new Promise(r => chrome.storage.local.set(obj, r)); }

async function getClientId() {
  const v = await getStore([CLIENT_ID_KEY]);
  if (v[CLIENT_ID_KEY]) return v[CLIENT_ID_KEY];
  const id = crypto.randomUUID();
  await setStore({ [CLIENT_ID_KEY]: id });
  return id;
}
async function getSeq() {
  const v = await getStore([SEQ_KEY]);
  return typeof v[SEQ_KEY] === "number" ? v[SEQ_KEY] : 0;
}
async function setSeq(n) { return setStore({ [SEQ_KEY]: n }); }
async function getPending() {
  const v = await getStore([PENDING_KEY]);
  return v[PENDING_KEY] || {};
}
async function setPending(obj) { return setStore({ [PENDING_KEY]: obj }); }

// --- Sequence handshake (bootstrap or recovery) ---
async function handshakeSeq() {
  const clientId = await getClientId();
  let serverLast = 0;
  try {
    const r = await fetch(`${COLLECTOR}/client_status?client_id=${encodeURIComponent(clientId)}`, {
      headers: { "X-API-KEY": API_KEY }
    });
    if (r.ok) {
      const j = await r.json();
      serverLast = j.last_seq | 0;
    }
  } catch {}
  await setSeq(serverLast);
  if (DEBUG) console.log("[LLM-UC] handshake: server last_seq =", serverLast);
}

// --- Pending ops ---
async function incrementPending(host, delta = 1) {
  const p = await getPending();
  p[host] = (p[host] || 0) + delta;
  await setPending(p);
  schedulePush();
}

// --- Coalesced push ---
let pushTimerHandle = null;
function schedulePush() {
  if (pushTimerHandle) clearTimeout(pushTimerHandle);
  pushTimerHandle = setTimeout(pushToCollector, PUSH_COALESCE_MS);
}

async function pushToCollector() {
  try {
    const [clientId, seq, pending] = await Promise.all([getClientId(), getSeq(), getPending()]);
    // Build snapshot of nonzero deltas
    const snapshot = {};
    for (const [k, vRaw] of Object.entries(pending || {})) {
      const v = vRaw | 0;
      if (v > 0) snapshot[k] = v;
    }
    if (Object.keys(snapshot).length === 0) return;

    const res = await fetch(`${COLLECTOR}/add`, {
      method: "POST",
      headers: { "Content-Type":"application/json", "X-API-KEY": API_KEY },
      body: JSON.stringify({ ts: Date.now(), client_id: clientId, seq: seq + 1, deltas: snapshot })
    });

    if (res.status === 200) {
      const rsp = await res.json().catch(()=>({}));
      await setSeq(rsp.last_seq ?? (seq + 1));

      // subtract exactly what we just sent
      const cur = await getPending();
      for (const k of Object.keys(snapshot)) {
        cur[k] = Math.max(0, (cur[k] || 0) - snapshot[k]);
        if (cur[k] === 0) delete cur[k];
      }
      await setPending(cur);
      if (DEBUG) console.log("[LLM-UC] add ok; seq advanced; pending reduced:", snapshot);
    } else if (res.status === 409) {
      const j = await res.json().catch(()=>({}));
      const expected = j.expected_next | 0;
      if (expected > 0) {
        await setSeq(expected - 1);
        if (DEBUG) console.log("[LLM-UC] out-of-order; aligning seq to", expected - 1, "and retrying");
        schedulePush();
      }
    } else {
      if (DEBUG) console.log("[LLM-UC] add failed:", res.status);
    }
  } catch (e) {
    if (DEBUG) console.log("[LLM-UC] add error:", e);
  }
}

// --- Network listener (only count real user sends) ---
chrome.webRequest.onBeforeRequest.addListener(
  (d) => {
    try {
      if (d.method !== "POST") return;
      const u = new URL(d.url);

      if (deniedByHost(u)) { dbgPush("host-deny", d, u, "deny rule"); return; }
      if (!allowedByHost(u)) { dbgPush("not-allowlisted", d, u, "no allow"); return; }
      if (!passesDebounce(d, u)) { dbgPush("debounced", d, u, `window=${DEDUPE_WINDOW_MS}ms`); return; }

      incrementPending(u.hostname, 1);
      dbgPush("counted", d, u, null);
    } catch (e) {
      if (DEBUG) console.log("[LLM-UC] onBeforeRequest error", e);
    }
  },
  { urls: URL_FILTERS },
  []
);

// --- Bootstrap / recovery ---
chrome.runtime.onInstalled?.addListener(handshakeSeq);
chrome.runtime.onStartup?.addListener(handshakeSeq);

// Try to drain pending whenever SW wakes
chrome.runtime.onInstalled?.addListener(() => schedulePush());
chrome.runtime.onStartup?.addListener(() => schedulePush());

// --- Popup API (optional, keep if your popup uses it) ---
chrome.runtime.onMessage.addListener((m, s, send) => {
  if (m && m.cmd === "get_status") {
    Promise.all([getPending(), getSeq(), getClientId()]).then(async ([pending, seq, client_id]) => {
      // Fetch server totals for display
      let serverCounters = {};
      try {
        const r = await fetch(`${COLLECTOR}/counters`, { headers: { "X-API-KEY": API_KEY } });
        if (r.ok) {
          const j = await r.json();
          serverCounters = j.counters || {};
        }
      } catch {}
      send({ client_id, seq, pending, serverCounters, debug: debugBuf });
    });
    return true;
  } else if (m && m.cmd === "force_push") {
    schedulePush();
    send({ ok: true });
    return true;
  } else if (m && m.cmd === "clear_pending") {
    setPending({}).then(() => send({ ok: true }));
    return true;
  }
});
