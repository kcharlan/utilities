# collector/collector.py
# Server is sole source of truth.
# - Totals live on the server and persist to state.json
# - Clients send idempotent "add" batches with a per-client sequence number
# - Server stores last_seq per client to dedupe retries
# - Extras: /counters /add /client_status /reset /flush /health
#
# Run under gunicorn in Docker (recommended), or directly for dev.

import os
import json
import tempfile
import threading
import signal
import atexit
from datetime import datetime, timezone
from typing import Dict, Any

from flask import Flask, request, jsonify, abort

# -----------------------
# Configuration
# -----------------------
APP_ROOT     = os.path.abspath(os.getenv("APP_ROOT", os.getcwd()))
STATE_PATH   = os.path.abspath(os.getenv("STATE_PATH", os.path.join(APP_ROOT, "state.json")))
SNAP_DIR     = os.path.abspath(os.getenv("SNAP_DIR", os.path.join(APP_ROOT, "snapshots")))
LOG_PATH     = os.path.abspath(os.getenv("LOG_PATH", os.path.join(APP_ROOT, "collector.log")))
API_KEY_ENV  = os.getenv("API_KEY", "")
def _get_env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

LOG_MAX_BYTES    = max(_get_env_int("LOG_MAX_BYTES", 10 * 1024 * 1024), 0)
LOG_BACKUP_COUNT = max(_get_env_int("LOG_BACKUP_COUNT", 5), 0)

# -----------------------
# Logging
# -----------------------
_log_lock = threading.RLock()
def _ensure_log_dir() -> None:
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

def _maybe_rotate_locked(incoming_len: int) -> None:
    if LOG_MAX_BYTES <= 0:
        return
    try:
        current_size = os.path.getsize(LOG_PATH)
    except FileNotFoundError:
        return
    except OSError:
        return
    if current_size + incoming_len <= LOG_MAX_BYTES:
        return

    try:
        if LOG_BACKUP_COUNT > 0:
            oldest = f"{LOG_PATH}.{LOG_BACKUP_COUNT}"
            if os.path.exists(oldest):
                os.remove(oldest)
            for idx in range(LOG_BACKUP_COUNT - 1, 0, -1):
                src = f"{LOG_PATH}.{idx}"
                if os.path.exists(src):
                    os.replace(src, f"{LOG_PATH}.{idx + 1}")
            os.replace(LOG_PATH, f"{LOG_PATH}.1")
        else:
            os.remove(LOG_PATH)
    except OSError:
        pass

def log(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    msg = f"{ts} {line}"
    with _log_lock:
        try:
            _ensure_log_dir()
            _maybe_rotate_locked(len(msg) + 1)
            with open(LOG_PATH, "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass
    print(msg, flush=True)

# -----------------------
# Persistent state (SOT)
# STATE = {
#   "totals": {host:int, ...},
#   "clients": { client_id: {"last_seq": int} }
# }
# -----------------------
_state_lock = threading.RLock()
STATE: Dict[str, Any] = {
    "totals": {},
    "clients": {}
}

def _atomic_write(path: str, data_dict: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_state_", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data_dict, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {"totals": {}, "clients": {}}
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f) or {}
        data.setdefault("totals", {})
        data.setdefault("clients", {})
        # normalize ints
        data["totals"] = {str(k): int(v) for k, v in data["totals"].items()}
        for cid, meta in list(data["clients"].items()):
            if not isinstance(meta, dict):
                data["clients"][cid] = {"last_seq": 0}
            else:
                meta["last_seq"] = int(meta.get("last_seq", 0))
        return data
    except Exception as e:
        log(f"[WARN] failed to load {STATE_PATH}: {e}")
        return {"totals": {}, "clients": {}}

def save_state() -> None:
    with _state_lock:
        _atomic_write(STATE_PATH, STATE)

def snapshot_totals() -> str:
    os.makedirs(SNAP_DIR, exist_ok=True)
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    snap = os.path.join(SNAP_DIR, f"snapshot_{ts}.json")
    with _state_lock:
        _atomic_write(snap, {"totals": STATE["totals"]})
    return snap

# -----------------------
# Flask app
# -----------------------
app = Flask(__name__)

def _auth_or_403(req):
    if not API_KEY_ENV:
        return
    if req.headers.get("X-API-KEY") != API_KEY_ENV:
        abort(403)

@app.before_request
def _preflight():
    cl = request.content_length
    if cl is not None and cl > 1024 * 1024:
        abort(413)

@app.get("/health")
def health():
    return jsonify({"ok": True}), 200

@app.get("/counters")
def get_counters():
    _auth_or_403(request)
    with _state_lock:
        return jsonify({"counters": dict(STATE["totals"])}), 200

@app.get("/client_status")
def client_status():
    _auth_or_403(request)
    cid = request.args.get("client_id", "")
    if not cid:
        return jsonify({"error": "missing client_id"}), 400
    with _state_lock:
        last_seq = int(STATE["clients"].get(cid, {}).get("last_seq", 0))
    return jsonify({"client_id": cid, "last_seq": last_seq}), 200

@app.post("/add")
def add():
    """
    Idempotent atomic add with per-client sequencing.

    Body:
      {
        "client_id": "uuid",
        "seq": <int>,            # client's next sequence (monotonic per client)
        "deltas": { "host": +n, ... },
        "ts": <ms since epoch>   # optional
      }

    Behavior:
      - If seq <= last_seq: treat as retry; ignore deltas, return 200.
      - If seq == last_seq + 1: apply deltas atomically to totals; set last_seq=seq; return 200.
      - If seq > last_seq + 1: out of order; return 409 with expected_next.
    """
    _auth_or_403(request)
    p = request.get_json(force=True, silent=True) or {}
    cid = p.get("client_id")
    seq = p.get("seq")
    deltas = p.get("deltas") or {}

    if not cid or not isinstance(deltas, dict):
        return jsonify({"error": "bad payload"}), 400
    try:
        seq = int(seq)
    except Exception:
        return jsonify({"error": "bad seq"}), 400

    with _state_lock:
        meta = STATE["clients"].setdefault(cid, {"last_seq": 0})
        last_seq = int(meta.get("last_seq", 0))

        if seq <= last_seq:
            log(f"[ADD] client={cid} seq={seq} <= last_seq={last_seq} (duplicate) — no-op")
            return jsonify({"ok": True, "applied": 0, "last_seq": last_seq}), 200

        if seq > last_seq + 1:
            log(f"[ADD] client={cid} seq={seq} > last_seq+1={last_seq+1} (out of order)")
            return jsonify({"error": "out_of_order", "expected_next": last_seq + 1}), 409

        # seq == last_seq + 1 → apply
        applied = 0
        for host, dv in deltas.items():
            try:
                d = int(dv)
            except Exception:
                continue
            if d > 0:
                h = str(host)
                STATE["totals"][h] = STATE["totals"].get(h, 0) + d
                applied += d

        meta["last_seq"] = seq
        save_state()

    ts = p.get("ts")
    try:
        ts_iso = datetime.fromtimestamp(ts/1000.0, tz=timezone.utc).isoformat() if isinstance(ts, (int,float)) else "n/a"
    except Exception:
        ts_iso = "n/a"

    log(f"[ADD] client={cid} seq={seq} applied={applied} ts={ts_iso}")
    return jsonify({"ok": True, "applied": applied, "last_seq": seq}), 200

@app.post("/reset")
def reset():
    _auth_or_403(request)
    snap = snapshot_totals()
    with _state_lock:
        STATE["totals"].clear()
        STATE["clients"].clear()
        save_state()
    log(f"[RESET] snapshot={snap}")
    return jsonify({"ok": True, "snapshot": snap}), 200

@app.post("/flush")
def flush():
    _auth_or_403(request)
    save_state()
    log("[FLUSH] state.json written")
    return jsonify({"ok": True}), 200

# -----------------------
# Startup / Shutdown
# -----------------------
def _graceful_flush(signame: str):
    try:
        save_state()
        log(f"[SHUTDOWN] {signame}: state flushed")
    except Exception as e:
        log(f"[SHUTDOWN] {signame}: flush failed: {e}")

def _install_signal_handlers():
    for sig in ("SIGTERM", "SIGINT"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), lambda *_: _graceful_flush(sig))

def _atexit_flush():
    _graceful_flush("atexit")

def _init():
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)
    loaded = load_state()
    with _state_lock:
        STATE.clear()
        STATE.update(loaded)
    log("[INIT] collector started; state loaded; paths: "
        f"STATE_PATH={STATE_PATH} SNAP_DIR={SNAP_DIR} LOG_PATH={LOG_PATH}")

_init()
_install_signal_handlers()
atexit.register(_atexit_flush)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, threaded=True)
