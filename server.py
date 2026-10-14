import json
import mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
MODEL = "qwen3:4b"
MAX_BODY_BYTES = 1_000_000

DESIGNER_PROMPT = """You are an expert residential interior designer and space planner.
Create practical, visually cohesive proposals that respect the user's exact room dimensions.
Always answer every explicit question in the user's latest message directly. Missing room
dimensions are not a reason to withhold general design advice: explain what can be answered
now, and ask only for details needed to make a dimension-specific layout. Never invent
measurements or house details. Do not ask again for details the user already supplied. If the
user wants to proceed with incomplete information, clearly state assumptions and label
dimension-specific suggestions provisional.
Give the final answer only: never include hidden reasoning, analysis, scratch notes, or
text inside <think> tags. Keep simple answers concise; reserve detailed sections for complete
home-design proposals.

For a complete proposal, cover: overall concept and color/material palette; room-by-room
furniture placement with realistic furniture sizes; circulation clearances and door/window
access; built-in storage, wardrobes, kitchen and utility; ambient, task and accent lighting;
floor, wall, ceiling, curtains and decor; natural light, ventilation, privacy and spaciousness;
a practical shopping/specification list; budget-friendly alternatives; and a separate,
ready-to-use image-generation prompt for each room. Respect the stated budget, climate,
occupants, preferences, existing furniture and must-haves. Prioritize safety, easy
maintenance and usable storage. State when exact site measurements or professional review
are needed. Use clear headings and actionable advice, and avoid claiming that a layout fits
unless the provided dimensions support it."""


class ChatHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_GET(self):
        if self.path == "/api/health":
            self.send_health()
            return
        if self.path.startswith("/api/"):
            self.send_json({"error": "Not found."}, 404)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_json({"error": "Not found."}, 404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "Invalid request size."}, 400)
            return
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self.send_json({"error": "Request must be between 1 byte and 1 MB."}, 413)
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json({"error": "Request body must be valid JSON."}, 400)
            return

        messages = payload.get("messages") if isinstance(payload, dict) else None
        if not isinstance(messages, list) or not messages or len(messages) > 60:
            self.send_json({"error": "Provide between 1 and 60 chat messages."}, 400)
            return

        cleaned_messages = [{"role": "system", "content": DESIGNER_PROMPT}]
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                self.send_json({"error": "Each message must be an object."}, 400)
                return
            role = message.get("role")
            content = message.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
                self.send_json({"error": "Messages need a user or assistant role and non-empty text."}, 400)
                return
            if len(content) > 20_000:
                self.send_json({"error": "Each message must be 20,000 characters or fewer."}, 413)
                return
            if index == len(messages) - 1 and role == "user":
                content = f"/no_think\n{content}"
            cleaned_messages.append({"role": role, "content": content})

        request_body = json.dumps({
            "model": MODEL,
            "messages": cleaned_messages,
            "stream": True,
            "think": False,
            "options": {"num_predict": 2048},
        }).encode("utf-8")
        request = Request(
            OLLAMA_CHAT_URL,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response_started = False
        try:
            with urlopen(request, timeout=180) as response:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                response_started = True
                pending = ""
                suppressed_content = ""
                inside_thinking = True
                saw_thinking_end = False

                def emit_content(content):
                    if content:
                        chunk = json.dumps({"message": {"content": content}}).encode("utf-8") + b"\n"
                        self.wfile.write(chunk)
                        self.wfile.flush()

                def filter_content(content):
                    nonlocal pending, suppressed_content, inside_thinking, saw_thinking_end
                    pending += content
                    while True:
                        marker = "</think>" if inside_thinking else "<think>"
                        marker_index = pending.find(marker)
                        if marker_index == -1:
                            safe_length = max(0, len(pending) - len(marker) + 1)
                            if inside_thinking:
                                suppressed_content += pending[:safe_length]
                            else:
                                emit_content(pending[:safe_length])
                            pending = pending[safe_length:]
                            return
                        if inside_thinking:
                            suppressed_content += pending[:marker_index]
                            suppressed_content = ""
                            pending = pending[marker_index + len(marker):]
                            inside_thinking = False
                            saw_thinking_end = True
                        else:
                            emit_content(pending[:marker_index])
                            pending = pending[marker_index + len(marker):]
                            inside_thinking = True

                for line in response:
                    if line.strip():
                        ollama_chunk = json.loads(line)
                        content = ollama_chunk.get("message", {}).get("content")
                        if isinstance(content, str):
                            filter_content(content)
                if not inside_thinking:
                    emit_content(pending)
                elif not saw_thinking_end and "<think>" not in suppressed_content + pending:
                    emit_content(suppressed_content + pending)
                else:
                    error_line = json.dumps({
                        "error": "The model did not finish a clean answer. Please try again."
                    }).encode("utf-8") + b"\n"
                    self.wfile.write(error_line)
                    self.wfile.flush()
                self.close_connection = True
                return
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            self.send_json({"error": f"Ollama returned HTTP {error.code}: {detail[:500]}"}, 502)
            return
        except (URLError, TimeoutError, OSError) as error:
            if response_started:
                error_line = json.dumps({"error": f"Ollama response interrupted: {error}"}).encode("utf-8") + b"\n"
                try:
                    self.wfile.write(error_line)
                    self.wfile.flush()
                except OSError:
                    pass
                return
            self.send_json({
                "error": f"Could not reach Ollama at localhost:11434. Make sure Ollama is running. Details: {error}"
            }, 502)
            return
        except json.JSONDecodeError as error:
            if response_started:
                error_line = json.dumps({"error": f"Ollama returned invalid stream data: {error}"}).encode("utf-8") + b"\n"
                self.wfile.write(error_line)
                self.wfile.flush()
                return
            self.send_json({"error": f"Ollama returned invalid JSON: {error}"}, 502)
            return

    def send_health(self):
        try:
            with urlopen(OLLAMA_TAGS_URL, timeout=5) as response:
                tags = json.loads(response.read())
            available = any(model.get("name") == MODEL for model in tags.get("models", []))
            self.send_json({
                "ok": available,
                "model": MODEL,
                "error": None if available else f"{MODEL} is not available in Ollama.",
            })
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            self.send_json({
                "ok": False,
                "model": MODEL,
                "error": f"Ollama is not responding at localhost:11434. {error}",
            })

    def send_json(self, data, status=200):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format_string, *args):
        print(f"{self.log_date_time_string()} - {format_string % args}")


if __name__ == "__main__":
    mimetypes.add_type("text/javascript", ".js")
    server = ThreadingHTTPServer(("127.0.0.1", 8000), ChatHandler)
    print(f"Interior Designer AI is ready: http://127.0.0.1:8000 (model: {MODEL})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Interior Designer AI.")
    finally:
        server.server_close()
