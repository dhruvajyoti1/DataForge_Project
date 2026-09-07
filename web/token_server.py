import json
import os
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from livekit.api import AccessToken, VideoGrants

LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    raise RuntimeError("Missing LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET env vars.")


def generate_token(room_name: str, identity: str) -> str:
    grants = VideoGrants(
        room_join=True,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        room=room_name,
    )
    token = (
        AccessToken(api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
        .with_grants(grants=grants)
        .with_identity(identity=identity)
        .with_ttl(ttl=timedelta(minutes=30))
    )
    return token.to_jwt()


class TokenHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/token":
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')
            return

        qs = parse_qs(parsed.query)
        room_name = qs.get("room", ["echoassist-demo"])[0]
        identity = qs.get("identity", [f"user-{uuid.uuid4().hex[:8]}"])[0]

        try:
            jwt_token = generate_token(room_name, identity)
            body = json.dumps({"token": jwt_token, "serverUrl": LIVEKIT_URL}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(500)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        print(f"[token_server] {self.address_string()} - {format % args}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), TokenHandler)
    print(f"Token server running on port {port}")
    server.serve_forever() 
