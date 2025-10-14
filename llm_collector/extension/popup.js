// popup.js — MV3-safe messaging with timeouts + defensive DOM guards

function $(id){ return document.getElementById(id); }
function fmt(ts){ if(!ts) return "—"; const d=new Date(ts); return d.toLocaleString(); }

function renderStatus(data){
  const { serverCounters = {}, pending = {}, seq = 0, client_id = "—", debug = [] } = data || {};
  const list = $("list"); if (!list) return;
  const frag = document.createDocumentFragment();

  const totalsEntries = Object.entries(serverCounters).sort((a,b)=>b[1]-a[1]);
  const serverTitle = document.createElement("div");
  serverTitle.innerHTML = "<b>Server totals</b>";
  frag.appendChild(serverTitle);
  if (totalsEntries.length === 0){
    const row = document.createElement("div"); row.textContent = "(none yet)";
    frag.appendChild(row);
  } else {
    for (const [h,c] of totalsEntries.slice(0,10)){
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span title="${h}">${h}</span><span>${c}</span>`;
      frag.appendChild(row);
    }
  }

  const pendingEntries = Object.entries(pending).sort((a,b)=>b[1]-a[1]);
  const pendTitle = document.createElement("div");
  pendTitle.style.marginTop = "10px";
  pendTitle.innerHTML = "<b>Pending (unsent)</b>";
  frag.appendChild(pendTitle);
  if (pendingEntries.length === 0){
    const row = document.createElement("div"); row.textContent = "(none)";
    frag.appendChild(row);
  } else {
    for (const [h,c] of pendingEntries.slice(0,10)){
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span title="${h}">${h}</span><span>${c}</span>`;
      frag.appendChild(row);
    }
  }

  const meta = document.createElement("div");
  meta.style.marginTop = "10px";
  meta.innerHTML = `<small>client_id: ${client_id}<br/>seq: ${seq}<br/>debug records: ${debug?.length ?? 0}</small>`;
  frag.appendChild(meta);

  list.innerHTML = "";
  list.appendChild(frag);
}

function sendMessageWithTimeout(msg, timeoutMs = 2000){
  return new Promise((resolve, reject) => {
    let done = false;
    const timer = setTimeout(() => {
      if (done) return; done = true; reject(new Error("timeout"));
    }, timeoutMs);

    try {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (done) return; done = true; clearTimeout(timer);
        const err = chrome.runtime.lastError;
        if (err) return reject(new Error(err.message || "lastError"));
        resolve(resp || {});
      });
    } catch (e){
      if (done) return; done = true; clearTimeout(timer); reject(e);
    }
  });
}

async function refresh(){
  const statusEl = $("status"); if (statusEl) statusEl.textContent = "Loading…";
  try {
    const resp = await sendMessageWithTimeout({ cmd: "get_status" }, 3000);
    if (statusEl) statusEl.textContent = "OK";
    renderStatus(resp);
  } catch (e){
    if (statusEl) statusEl.textContent = `Error: ${e.message}`;
    const list = $("list");
    if (list) {
      list.innerHTML = `
        <div style="color:#c00; font-size:12px; line-height:1.4;">
          • If this says <i>"The message port closed before a response was received."</i>:
          <br/>— Ensure <code>background.js</code> handles <code>get_status</code> and returns <code>true</code>.
          <br/>— Click "Reload" to retry (wakes the service worker).
          <br/>— Or reload the extension from <code>vivaldi://extensions</code> and reopen the popup.
        </div>`;
    }
  }
}

function bind(id, event, fn){
  const el = $(id);
  if (el) el.addEventListener(event, fn);
}

document.addEventListener("DOMContentLoaded", () => {
  bind("reset", "click", async () => {
    const st = $("status"); if (st) st.textContent = "Clearing pending…";
    try { await sendMessageWithTimeout({ cmd: "clear_pending" }, 2000); } catch {}
    refresh();
  });

  bind("export", "click", async () => {
    const st = $("status"); if (st) st.textContent = "Refreshing…";
    try {
      const resp = await sendMessageWithTimeout({ cmd: "get_status" }, 3000);
      const out = $("out");
      if (out) {
        out.value = JSON.stringify({
          serverCounters: resp.serverCounters || {},
          pending: resp.pending || {},
          seq: resp.seq,
          client_id: resp.client_id,
          debug: resp.debug || []
        }, null, 2);
        out.focus(); out.select(); document.execCommand("copy");
      }
      if (st) st.textContent = "Copied JSON to clipboard.";
    } catch (e){
      if (st) st.textContent = `Export failed: ${e.message}`;
    }
  });

  bind("forcePush", "click", async () => {
    const st = $("status"); if (st) st.textContent = "Pushing…";
    try {
      await sendMessageWithTimeout({ cmd: "force_push" }, 2000);
      setTimeout(refresh, 300); // allow background to POST, then refresh
    } catch (e){
      if (st) st.textContent = `Push failed: ${e.message}`;
    }
  });

  bind("reload", "click", () => refresh());

  // initial load
  refresh();
});
