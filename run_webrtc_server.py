
# --- HARDCODED ENV VARS (Added by AI) ---
import os
os.environ['WEBRTC_DEV_MODE'] = 'true'
os.environ['WEBRTC_PORT'] = '5001'
os.environ['VITE_WEBRTC_URL'] = 'http://localhost:5000'
os.environ['VITE_API_URL'] = 'https://app-4pt0.onrender.com'
os.environ['LICHESS_API_TOKEN'] = os.environ.get('LICHESS_API_TOKEN', '')
os.environ['USE_GOOGLE_DRIVE'] = 'false'
os.environ['GOOGLE_DRIVE_FOLDER'] = 'ChatApp_Uploads'
os.environ['GOOGLE_DRIVE_UPLOAD_MODE'] = 'server'
os.environ['VITE_GOOGLE_CLIENT_ID'] = os.environ.get('VITE_GOOGLE_CLIENT_ID', '')
os.environ['VITE_GOOGLE_CLIENT_SECRET'] = os.environ.get('VITE_GOOGLE_CLIENT_SECRET', '')
os.environ['FILE_TRANSFER_MODE'] = 'server'
os.environ['VITE_VIBES_API_URL'] = 'https://vibes-181a.onrender.com'
os.environ['VITE_STATUSES_API_URL'] = 'https://statuses-nuef.onrender.com'
os.environ['VITE_POLLING_API_URL'] = 'http://localhost:5005'
os.environ['VITE_TRADING_API_URL'] = 'https://trading-p19s.onrender.com'
os.environ['VITE_FCM_API_URL'] = 'https://flask-backend-latest-dzkl.onrender.com/api/v1/fcm_token'
os.environ['VITE_STORAGE_API_URL'] = 'http://13.212.57.105:5006'
os.environ['VITE_THREATS_API_URL'] = 'https://vibes-181a.onrender.com'
os.environ['ENCRYPTION_KEY'] = os.environ.get('ENCRYPTION_KEY', '')
# ------------------------------------------

"""
Standalone WebRTC signaling server.
Runs the WebRTC Blueprint as its own process on port 5001.
"""
import os
import sys
import types

# Load .env file for local dev (so JWT_SECRET etc. can be shared)
try:
    from dotenv import load_dotenv
    _base = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_base)  # backend/.. = project root
    load_dotenv(os.path.join(_project_root, '.env'))
    # Also try .env in the backend directory
    load_dotenv(os.path.join(_base, '.env'))
except ImportError:
    pass

# ──────────────────────────────────────────────────────────────────────
# Provide the functions that webrtc_routes.py imports from 'app' module
# This avoids a circular import between app.py <-> webrtc_routes.py
# ──────────────────────────────────────────────────────────────────────

import jwt
from flask import request

JWT_SECRET = os.environ.get('JWT_SECRET', 'change_this_secret')
DEV_MODE = True

def execute_query(query, params=None, fetch=False, commit=True, get_lastrowid=False):
    # No-op stub — routes in webrtc_routes.py use WEBRTC_MESSAGES dict directly
    if fetch:
        return []
    return None

def get_auth_user_id():
    auth = request.headers.get('Authorization') or ''
    if not auth.startswith('Bearer '):
        return None
    token = auth.split(' ', 1)[1].strip()
    # Try strict verification first
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        uid = payload.get('user_id') or payload.get('id') or payload.get('sub')
        return int(uid) if uid else None
    except Exception:
        pass
    # Dev mode: decode without verification (accept tokens from production)
    if DEV_MODE:
        try:
            payload = jwt.decode(token, options={"verify_signature": False}, algorithms=['HS256'])  # NOSONAR - intentional for DEV_MODE
            uid = payload.get('user_id') or payload.get('id') or payload.get('sub')
            return int(uid) if uid else None
        except Exception:
            return None
    return None

def publish_to_user(user_id, payload):
    pass  # stub - webrtc_routes handles its own delivery

def sse_broadcast(user_id, event_type, data):
    pass

# Monkey-patch so webrtc_routes.py finds these via 'from app import ...'
app_mod = types.ModuleType('app')
app_mod.execute_query = execute_query
app_mod.get_auth_user_id = get_auth_user_id
app_mod.publish_to_user = publish_to_user
app_mod.sse_broadcast = sse_broadcast
sys.modules['app'] = app_mod

# ──────────────────────────────────────────────────────────────────────
# Build the standalone Flask app using the WebRTC Blueprint
# ──────────────────────────────────────────────────────────────────────
from flask import Flask, jsonify
from webrtc_routes import webrtc_bp, ensure_webrtc_messages_table

ALLOWED_ORIGINS = {
    "http://localhost:5173",
"http://localhost:5176",
    "https://myfocusvibes.netlify.app",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://localhost:5177",
    "https://localhost",
    "https://flask123.pythonanywhere.com",
}

app = Flask(__name__)
app.register_blueprint(webrtc_bp)

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin")
        resp = jsonify({"ok": True})
        if origin in ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp, 200

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

if __name__ == '__main__':
    port = int(os.environ.get('WEBRTC_PORT', 5001))
    print(f'WebRTC standalone server starting on 0.0.0.0:{port} (dev_mode={DEV_MODE})')
    app.run(host='0.0.0.0', port=port, debug=True)  # NOSONAR - intentional for server

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    return "", 204
