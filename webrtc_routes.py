import json
import time
import uuid
import threading
import datetime
from flask import Blueprint, request, jsonify

webrtc_bp = Blueprint('webrtc', __name__)

# ---------------------------------------------------------------------------
# WEBRTC STATE (signaling + presence only — no message storage)
# ---------------------------------------------------------------------------
WEBRTC_SIGNALS = {}
WEBRTC_ONLINE = {}
WEBRTC_LOCK = threading.Lock()

WEBRTC_REQUESTS = {}
WEBRTC_REQUESTS_LOCK = threading.Lock()

_webrtc_presence = {}
_presence_lock = threading.Lock()
_presence_callbacks = []

# ---------------------------------------------------------------------------
# PRESENCE HELPERS
# ---------------------------------------------------------------------------
def _get_webrtc_config():
    return {"presence_ttl": 60, "heartbeat_interval": 30, "cleanup_interval": 10, "max_missed_heartbeats": 2}

def _set_user_online(user_id, socket_id=None, webrtc=False):
    with _presence_lock:
        prev = _webrtc_presence.get(user_id, {}).get("online", False)
        _webrtc_presence[user_id] = {"last_seen": time.time(), "online": True, "socket_id": socket_id, "webrtc_connected": webrtc, "missed_heartbeats": 0}
        if not prev:
            for cb in _presence_callbacks:
                try: cb(user_id, True)
                except Exception: pass

def _set_user_offline(user_id):
    with _presence_lock:
        if user_id in _webrtc_presence:
            _webrtc_presence[user_id]["online"] = False
            for cb in _presence_callbacks:
                try: cb(user_id, False)
                except Exception: pass

def _process_heartbeat(user_id):
    with _presence_lock:
        if user_id not in _webrtc_presence:
            _webrtc_presence[user_id] = {"last_seen": time.time(), "online": True, "socket_id": None, "webrtc_connected": False, "missed_heartbeats": 0}
        else:
            _webrtc_presence[user_id]["last_seen"] = time.time()
            _webrtc_presence[user_id]["missed_heartbeats"] = 0
        return True

def _is_user_online(user_id):
    cfg = _get_webrtc_config()
    with _presence_lock:
        if user_id not in _webrtc_presence: return False
        status = _webrtc_presence[user_id]
        if not status.get("online"): return False
        return time.time() - status.get("last_seen", 0) < cfg["presence_ttl"]

def _get_user_status(user_id):
    cfg = _get_webrtc_config()
    with _presence_lock:
        status = _webrtc_presence.get(user_id, {})
        elapsed = time.time() - status.get("last_seen", 0) if status else 0
        return {"online": status.get("online", False) and elapsed < cfg["presence_ttl"], "last_seen": status.get("last_seen", 0), "webrtc_connected": status.get("webrtc_connected", False), "elapsed": elapsed}

def _get_batch_status(user_ids):
    return {uid: _is_user_online(uid) for uid in user_ids}

def _cleanup_presence():
    cfg = _get_webrtc_config()
    with _presence_lock:
        now = time.time()
        for uid, st in _webrtc_presence.items():
            if now - st.get("last_seen", 0) > cfg["presence_ttl"] * cfg["max_missed_heartbeats"]:
                _webrtc_presence[uid]["online"] = False
                for cb in _presence_callbacks:
                    try: cb(uid, False)
                    except Exception: pass

def _start_presence_cleanup():
    cfg = _get_webrtc_config()
    def run():
        while True:
            time.sleep(cfg["cleanup_interval"])
            _cleanup_presence()
    threading.Thread(target=run, daemon=True).start()

_start_presence_cleanup()

# ---------------------------------------------------------------------------
# PRESENCE ENDPOINTS
# ---------------------------------------------------------------------------
@webrtc_bp.route("/webrtc/online", methods=["POST"])
def webrtc_online():
    from app import get_auth_user_id
    user_id = get_auth_user_id()
    if not user_id: return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    socket_id = data.get("socket_id")
    webrtc = data.get("webrtc", False)
    _set_user_online(user_id, socket_id, webrtc)
    return jsonify({"status": "online", "timestamp": time.time()})

@webrtc_bp.route("/webrtc/offline", methods=["POST"])
def webrtc_offline():
    from app import get_auth_user_id
    user_id = get_auth_user_id()
    if not user_id: return jsonify({"error": "unauthorized"}), 401
    _set_user_offline(user_id)
    return jsonify({"status": "offline"})

@webrtc_bp.route("/webrtc/heartbeat", methods=["POST"])
def webrtc_heartbeat():
    from app import get_auth_user_id
    user_id = get_auth_user_id()
    if not user_id: return jsonify({"error": "unauthorized"}), 401
    _process_heartbeat(user_id)
    return jsonify({"status": "ok", "timestamp": time.time()})

@webrtc_bp.route("/webrtc/status/<int:target_user_id>", methods=["GET"])
def webrtc_check_status(target_user_id):
    is_online = _is_user_online(target_user_id)
    return jsonify({"user_id": target_user_id, "online": is_online, "status": _get_user_status(target_user_id)})

@webrtc_bp.route("/webrtc/status/batch", methods=["POST"])
def webrtc_batch_status():
    user_ids = request.json or {}
    user_ids = user_ids.get("user_ids", [])
    status = _get_batch_status(user_ids)
    return jsonify({"users": status})

# ---------------------------------------------------------------------------
# LEGACY PRESENCE (compat)
# ---------------------------------------------------------------------------
@webrtc_bp.route("/users/heartbeat", methods=["POST"])
def heartbeat():
    d = request.json or {}
    uid = d.get("user_id")
    if uid is None: return jsonify({"error": "user_id required"}), 400
    uid, sid = int(uid), d.get("session_id") or str(uuid.uuid4())
    with WEBRTC_LOCK: WEBRTC_ONLINE[uid] = {"last_seen": time.time(), "session_id": sid, "online": True}
    return jsonify({"user_id": uid, "online": True, "session_id": sid})

@webrtc_bp.route("/users/<int:user_id>/online", methods=["GET"])
def check_online(user_id):
    with WEBRTC_LOCK:
        data = WEBRTC_ONLINE.get(user_id, {})
        online = (time.time() - data.get("last_seen", 0)) < 60 if data else False
    return jsonify({"user_id": user_id, "online": online, "last_seen": data.get("last_seen") if data else None})

@webrtc_bp.route("/users/online/batch", methods=["POST"])
def batch_online():
    uids = request.json or {}
    results = {}
    with WEBRTC_LOCK:
        for uid in uids.get("user_ids", []):
            uid = int(uid)
            data = WEBRTC_ONLINE.get(uid, {})
            results[uid] = {"online": (time.time() - data.get("last_seen", 0)) < 60 if data else False}
    return jsonify({"users": results, "timestamp": time.time()})

# ---------------------------------------------------------------------------
# LEGACY SIGNAL ENDPOINTS (compat with older clients)
# ---------------------------------------------------------------------------
@webrtc_bp.route("/signal/msg/offer", methods=["POST"])
def signal_offer():
    d = request.json or {}
    f, t, offer = d.get("from_id"), d.get("to_id"), d.get("offer")
    ch = d.get("channel_id") or _channel_id(f, t)
    with WEBRTC_LOCK:
        k = (int(t), ch)
        WEBRTC_SIGNALS.setdefault(k, []).append({"from_id": int(f), "type": "offer", "data": offer, "timestamp": time.time(), "channel_id": ch})
    return jsonify({"channel_id": ch, "stored": True}), 201

@webrtc_bp.route("/signal/msg/answer", methods=["POST"])
def signal_answer():
    d = request.json or {}
    f, t, ans, ch = d.get("from_id"), d.get("to_id"), d.get("answer"), d.get("channel_id")
    with WEBRTC_LOCK:
        k = (int(t), ch)
        WEBRTC_SIGNALS.setdefault(k, []).append({"from_id": int(f), "type": "answer", "data": ans, "timestamp": time.time(), "channel_id": ch})
    return jsonify({"stored": True}), 201

@webrtc_bp.route("/signal/msg/ice", methods=["POST"])
def signal_ice():
    d = request.json or {}
    f, t, cand, ch = d.get("from_id"), d.get("to_id"), d.get("candidate"), d.get("channel_id")
    with WEBRTC_LOCK:
        k = (int(t), ch)
        WEBRTC_SIGNALS.setdefault(k, []).append({"from_id": int(f), "type": "ice", "data": cand, "timestamp": time.time(), "channel_id": ch})
    return jsonify({"stored": True}), 201

@webrtc_bp.route("/signal/msg/<int:user_id>", methods=["GET"])
def poll_signals(user_id):
    ch = request.args.get("channel_id")
    since = request.args.get("since", type=float)
    signals = []
    with WEBRTC_LOCK:
        for k, sigs in WEBRTC_SIGNALS.items():
            if k[0] != user_id: continue
            if ch and k[1] != ch: continue
            signals.extend([s for s in sigs if not since or s["timestamp"] > since])
    signals.sort(key=lambda x: x["timestamp"])
    return jsonify({"signals": signals, "count": len(signals), "timestamp": time.time()})

@webrtc_bp.route("/signal/msg/clear", methods=["POST"])
def clear_signals():
    d = request.json or {}
    uid, ch = d.get("user_id"), d.get("channel_id")
    ts = d.get("before_timestamp")
    with WEBRTC_LOCK:
        k = (int(uid), ch)
        if k in WEBRTC_SIGNALS:
            WEBRTC_SIGNALS[k] = [s for s in WEBRTC_SIGNALS[k] if not ts or s["timestamp"] > ts] if ts else []
    return jsonify({"cleared": len(WEBRTC_SIGNALS.get(k, []))})

def _channel_id(a, b):
    return f"msg_{min(a,b)}_{max(a,b)}"

# ---------------------------------------------------------------------------
# WEBRTC SIGNALING (data channel offer/answer/ICE)
# ---------------------------------------------------------------------------
@webrtc_bp.route("/webrtc/signal/offer", methods=["POST"])
def webrtc_signal_offer():
    from app import get_auth_user_id
    user_id = get_auth_user_id()
    if not user_id: return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    to_id = data.get("to_id")
    offer = data.get("offer")
    channel_id = data.get("channel_id") or f"{user_id}_{to_id}"
    with WEBRTC_LOCK:
        k = (int(to_id), channel_id)
        WEBRTC_SIGNALS.setdefault(k, []).append({"from_id": user_id, "type": "offer", "data": offer, "timestamp": time.time()})
    return jsonify({"channel_id": channel_id, "stored": True})

@webrtc_bp.route("/webrtc/signal/answer", methods=["POST"])
def webrtc_signal_answer():
    from app import get_auth_user_id
    user_id = get_auth_user_id()
    if not user_id: return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    to_id = data.get("to_id")
    answer = data.get("answer")
    channel_id = data.get("channel_id")
    with WEBRTC_LOCK:
        k = (int(to_id), channel_id)
        WEBRTC_SIGNALS.setdefault(k, []).append({"from_id": user_id, "type": "answer", "data": answer, "timestamp": time.time()})
    return jsonify({"stored": True})

@webrtc_bp.route("/webrtc/signal/ice", methods=["POST"])
def webrtc_signal_ice():
    from app import get_auth_user_id
    user_id = get_auth_user_id()
    if not user_id: return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    to_id = data.get("to_id")
    candidate = data.get("candidate")
    channel_id = data.get("channel_id")
    with WEBRTC_LOCK:
        k = (int(to_id), channel_id)
        WEBRTC_SIGNALS.setdefault(k, []).append({"from_id": user_id, "type": "ice", "data": candidate, "timestamp": time.time()})
    return jsonify({"stored": True})

@webrtc_bp.route("/webrtc/signal/<int:target_user_id>", methods=["GET"])
def webrtc_get_signals(target_user_id):
    channel_id = request.args.get("channel_id")
    with WEBRTC_LOCK:
        k = (target_user_id, channel_id)
        signals = WEBRTC_SIGNALS.get(k, [])
        WEBRTC_SIGNALS[k] = []
    return jsonify({"signals": signals})

# ---------------------------------------------------------------------------
# WEBRTC CONNECTION REQUEST (auto-connect pairing)
# ---------------------------------------------------------------------------
@webrtc_bp.route("/webrtc/request", methods=["POST"])
def webrtc_send_request():
    try:
        data = request.json or {}
        caller_id = data.get("caller_id")
        callee_id = data.get("callee_id")
        if not caller_id or not callee_id: return jsonify({"error": "caller_id and callee_id required"}), 400
        req_id = str(uuid.uuid4())
        with WEBRTC_REQUESTS_LOCK:
            WEBRTC_REQUESTS[req_id] = {"caller_id": int(caller_id), "callee_id": int(callee_id), "status": "pending", "created_at": time.time()}
        return jsonify({"request_id": req_id}), 201
    except Exception as e: return jsonify({"error": str(e)}), 500

@webrtc_bp.route("/webrtc/requests/incoming/<int:user_id>", methods=["GET"])
def webrtc_incoming_requests(user_id):
    try:
        with WEBRTC_REQUESTS_LOCK:
            pending = [{"request_id": rid, **info} for rid, info in WEBRTC_REQUESTS.items() if int(info["callee_id"]) == user_id and info["status"] == "pending"]
        return jsonify(pending), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

@webrtc_bp.route("/webrtc/request/respond", methods=["POST"])
def webrtc_respond_request():
    try:
        data = request.json or {}
        req_id = data.get("request_id")
        accept = data.get("accept")
        if not req_id or accept is None: return jsonify({"error": "request_id and accept required"}), 400
        with WEBRTC_REQUESTS_LOCK:
            req = WEBRTC_REQUESTS.get(req_id)
            if not req: return jsonify({"error": "Request not found"}), 404
            req["status"] = "accepted" if accept else "rejected"
        return jsonify({"status": req["status"]}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

@webrtc_bp.route("/webrtc/request/cancel", methods=["POST"])
def webrtc_cancel_request():
    try:
        data = request.json or {}
        req_id = data.get("request_id")
        if not req_id: return jsonify({"error": "request_id required"}), 400
        with WEBRTC_REQUESTS_LOCK: WEBRTC_REQUESTS.pop(req_id, None)
        return jsonify({"ok": True}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

@webrtc_bp.route("/webrtc/request/status/<int:caller_id>/<int:callee_id>", methods=["GET"])
def webrtc_request_status(caller_id, callee_id):
    try:
        with WEBRTC_REQUESTS_LOCK:
            for rid, info in WEBRTC_REQUESTS.items():
                if int(info["caller_id"]) == caller_id and int(info["callee_id"]) == callee_id:
                    return jsonify({"request_id": rid, **info}), 200
        return jsonify({"status": "none"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# AUTOMATIC CONNECTION PAIRING
# ---------------------------------------------------------------------------
@webrtc_bp.route("/webrtc/auto_connect", methods=["POST"])
def webrtc_auto_connect():
    try:
        from app import get_auth_user_id
        authed_user = get_auth_user_id()
        if not authed_user: return jsonify({"error": "unauthorized"}), 401
        data = request.json or {}
        user_a = authed_user
        user_b = data.get("peer_id")
        if not user_b: return jsonify({"error": "peer_id required"}), 400
        user_b = int(user_b)

        # Ensure caller is marked online (handles race between markOnline and this request)
        _set_user_online(user_a, webrtc=True)
        b_online = _is_user_online(user_b)
        if not b_online: return jsonify({"error": "Peer is offline"}), 400

        force = data.get("force", False)

        # If force, delete any existing request for this pair first
        if force:
            with WEBRTC_REQUESTS_LOCK:
                to_delete = []
                for rid, info in WEBRTC_REQUESTS.items():
                    if (info["caller_id"] == user_a and info["callee_id"] == user_b) or \
                       (info["caller_id"] == user_b and info["callee_id"] == user_a):
                        to_delete.append(rid)
                for rid in to_delete:
                    del WEBRTC_REQUESTS[rid]

        if not force:
            # Check for existing accepted connection
            with WEBRTC_REQUESTS_LOCK:
                for rid, info in WEBRTC_REQUESTS.items():
                    if info["status"] == "accepted" and (
                        (info["caller_id"] == user_a and info["callee_id"] == user_b) or
                        (info["caller_id"] == user_b and info["callee_id"] == user_a)
                    ):
                        return jsonify({"status": "already_connected", "request_id": rid}), 200

            # Check for pending request from A→B or B→A
            with WEBRTC_REQUESTS_LOCK:
                for rid, info in WEBRTC_REQUESTS.items():
                    if info["status"] == "pending":
                        if info["caller_id"] == user_a and info["callee_id"] == user_b:
                            return jsonify({"status": "pending", "request_id": rid, "direction": "outgoing"}), 200
                        if info["caller_id"] == user_b and info["callee_id"] == user_a:
                            return jsonify({"status": "pending", "request_id": rid, "direction": "incoming"}), 200

        # No existing request: create one automatically (lower ID initiates)
        initiator = min(user_a, user_b)
        receiver = max(user_a, user_b)
        req_id = str(uuid.uuid4())
        with WEBRTC_REQUESTS_LOCK:
            WEBRTC_REQUESTS[req_id] = {"caller_id": initiator, "callee_id": receiver, "status": "pending", "created_at": time.time()}
        return jsonify({"status": "created", "request_id": req_id, "initiator": initiator, "receiver": receiver}), 201

    except Exception as e: return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ACK SEEN / ACK DELIVERY (acknowledge from the other peer)
# ---------------------------------------------------------------------------
@webrtc_bp.route("/webrtc/ack_seen", methods=["POST"])
def webrtc_ack_seen():
    try:
        from app import get_auth_user_id
        if not get_auth_user_id(): return jsonify({"error": "unauthorized"}), 401
        data = request.json or {}
        other_id = data.get("other_id") or data.get("from_id")
        last_seen_id = data.get("last_seen_id") or data.get("lsid")
        conv = data.get("conv")
        seen_type = data.get("t", "seen")
        if not conv:
            return jsonify({"status": "ok"}), 200
        # Forward seen acknowledgment to the other user via pending messages
        # This tells the sender their message was seen
        with WEBRTC_LOCK:
            for uid, info in WEBRTC_ONLINE.items():
                if str(uid) == str(other_id):
                    # Store as a pending delivery notification
                    ch = f"ack_{conv}"
                    k = (int(other_id), ch)
                    WEBRTC_SIGNALS.setdefault(k, []).append({
                        "type": "seen_ack",
                        "conv": conv,
                        "last_seen_id": last_seen_id,
                        "t": seen_type,
                        "timestamp": time.time()
                    })
                    break
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@webrtc_bp.route("/webrtc/ack_delivery", methods=["POST"])
def webrtc_ack_delivery():
    try:
        from app import get_auth_user_id
        if not get_auth_user_id(): return jsonify({"error": "unauthorized"}), 401
        data = request.json or {}
        other_id = data.get("other_id") or data.get("from_id")
        last_delivered_id = data.get("last_delivered_id") or data.get("ldid")
        conv = data.get("conv")
        if not conv:
            return jsonify({"status": "ok"}), 200
        with WEBRTC_LOCK:
            for uid, info in WEBRTC_ONLINE.items():
                if str(uid) == str(other_id):
                    ch = f"ack_{conv}"
                    k = (int(other_id), ch)
                    WEBRTC_SIGNALS.setdefault(k, []).append({
                        "type": "delivery_ack",
                        "conv": conv,
                        "last_delivered_id": last_delivered_id,
                        "timestamp": time.time()
                    })
                    break
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def ensure_webrtc_messages_table():
    pass
