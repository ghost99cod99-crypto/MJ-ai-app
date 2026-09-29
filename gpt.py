import json, uuid, sys
import requests

BASE_URL = "https://android.chat.openai.com"
UA = "ChatGPT/1.2026.195 (Android 16; 2412DPC0AG; build 2619512)"

def fetch_models():
    try:
        s = requests.Session()
        s.headers.update({"accept": "application/json", "oai-client-type": "android",
                          "oai-package-name": "com.openai.chatgpt", "user-agent": UA})
        r = s.get(f"{BASE_URL}/backend-anon/models", params={"iim": "false", "supports_model_picker_upgrade_presets": "true"}, timeout=10)
        if r.status_code == 200:
            models = r.json().get("models", [])
            if models:
                return {str(i): {"slug": m["slug"], "name": m.get("title", m["slug"])} for i, m in enumerate(models, 1)}
    except Exception:
        pass
    return {"1": {"slug": "gpt-5-5", "name": "GPT-5.5"}, "2": {"slug": "gpt-5-3", "name": "GPT-5.3"},
            "3": {"slug": "gpt-5-mini", "name": "GPT-5-mini"}, "4": {"slug": "auto", "name": "Auto"}}

MODELS = fetch_models()

def parse_sse(chunks, on_delta=None):
    buf, events = "", []
    for chunk in chunks:
        buf += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            lines = block.strip().split("\n")
            evt_type, data_lines = "message", []
            for line in lines:
                if line.startswith("event: "): evt_type = line[7:].strip()
                elif line.startswith("data: "): data_lines.append(line[6:])
            if not data_lines: continue
            raw = "\n".join(data_lines)
            try: parsed = json.loads(raw)
            except json.JSONDecodeError: parsed = raw
            events.append((evt_type, parsed))
            if on_delta and evt_type == "delta":
                on_delta(parsed)
    return events

def extract_reply(events):
    parts, asst_msg = [], None
    for evt_type, d in events:
        if evt_type != "delta": continue
        if isinstance(d, str): parts.append(d); continue
        if not isinstance(d, dict): continue
        v = d.get("v")
        if isinstance(v, str): parts.append(v); continue
        if d.get("o") == "patch" and isinstance(v, list):
            for p in v:
                if isinstance(p, dict) and p.get("o") == "append" and "/parts/" in p.get("p", "") and isinstance(p.get("v"), str) and p["v"].strip():
                    parts.append(p["v"])
            continue
        if isinstance(v, dict) and d.get("o") != "patch":
            m = v.get("message", {})
            if isinstance(m, dict) and m.get("author", {}).get("role") in ("assistant", "system") and m.get("id"):
                ct = m.get("content", {}).get("content_type")
                if ct: asst_msg = m
    reply = "".join(parts)
    if asst_msg:
        ct = asst_msg.get("content", {})
        existing = ct.get("parts", [])
        if not any(p for p in existing if isinstance(p, str) and p.strip()):
            ct = {"content_type": "text", "parts": [reply] if reply else []}
        return reply, {
            "id": asst_msg["id"], "author": {"role": "assistant"},
            "content": ct,
            "status": "finished_successfully", "recipient": "all",
            "metadata": asst_msg.get("metadata", {}),
        }
    return reply, None

def stream_printer(d):
    if isinstance(d, str) and d.strip(): print(d, end="", flush=True); return
    if not isinstance(d, dict): return
    v = d.get("v")
    if isinstance(v, str) and v.strip(): print(v, end="", flush=True); return
    if d.get("o") == "patch" and isinstance(v, list):
        for p in v:
            if isinstance(p, dict) and p.get("o") == "append" and "/parts/" in p.get("p", "") and isinstance(p.get("v"), str) and p["v"].strip():
                print(p["v"], end="", flush=True)

def _base_body(model):
    return {"action": "next", "model": model, "history_and_training_disabled": False,
            "fork_from_shared_post": False, "enable_message_followups": False,
            "force_use_sse": False, "force_use_search": None, "force_paragen": False,
            "supported_encodings": ["v1"], "supports_buffering": True,
            "timezone": "Asia/Baghdad", "timezone_offset_min": -180,
            "system_hints": [], "is_onboarding_conversation": False,
            "no_auth_ad_preferences": {"personalization_enabled": True, "history_enabled": True}}

class ChatGPT:
    def __init__(self):
        self.device_id = str(uuid.uuid4())
        self.sess = requests.Session()
        self.sess.headers.update({"accept": "application/json", "accept-encoding": "gzip",
            "accept-language": "en-US,en;q=0.9", "cache-control": "no-cache",
            "content-type": "application/json", "chatgpt-account-id": "default",
            "chatgpt-residency-region": "no_constraint", "oai-client-type": "android",
            "oai-device-id": self.device_id, "oai-package-name": "com.openai.chatgpt",
            "user-agent": UA, "x-device-tier": "upper_mid"})
        self.conduit_token = self.conversation_id = self.parent_id = None
        self.history = []

    def _post(self, path, body=None):
        hdrs = {"x-openai-target-path": path}
        if self.conduit_token and "sentinel" not in path:
            hdrs["x-conduit-token"] = self.conduit_token
        r = self.sess.post(f"{BASE_URL}{path}", json=body or {}, headers=hdrs, timeout=60)
        r.raise_for_status()
        return r.json()

    def _stream(self, path, body):
        hdrs = {"x-openai-target-path": path}
        if self.conduit_token:
            hdrs["x-conduit-token"] = self.conduit_token
        return self.sess.post(f"{BASE_URL}{path}", json=body, headers=hdrs, stream=True, timeout=120)

    def chat(self, text, model="gpt-5-5", stream=False, first=False):
        if first:
            self.history = []
            self.parent_id = str(uuid.uuid4())
            self.conversation_id = str(uuid.uuid4())
            self._post("/backend-anon/sentinel/chat-requirements")
            self._post("/backend-anon/conversation/init", {})

        prep = _base_body(model) | {"conversation_id": self.conversation_id,
                                    "parent_message_id": self.parent_id,
                                    "client_prepare_dispatch": "debounced",
                                    "client_prepare_source": "composer_editor_state"}
        self.conduit_token = self._post("/backend-anon/f/conversation/prepare", prep)["conduit_token"]

        msg_id = str(uuid.uuid4())
        user_msg = {"id": msg_id, "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [text]},
                    "status": "finished_successfully", "recipient": "all",
                    "metadata": {"model_slug": model, "default_model_slug": model,
                        "is_visually_hidden_from_conversation": False,
                        "exclude_after_next_user_message": False, "content_references": [],
                        "search_result_groups": [], "search_queries": [], "image_results": [],
                        "dictation": False, "voice_mode_message": False, "image_gen_async": False,
                        "trigger_async_ux": False, "writing_blocks": {}}}
        self.history.append(user_msg)

        body = _base_body(model) | {"messages": list(self.history), "enable_message_followups": True,
                                    "force_use_sse": True, "client_prepare_state": "success", "stream": True}
        r = self._stream("/backend-anon/f/conversation", body)
        events = parse_sse(r.iter_content(chunk_size=None), on_delta=stream_printer if stream else None)
        if stream: print()

        reply, asst = extract_reply(events)
        if asst: self.history.append(asst)
        return reply, self.conversation_id

def show_models():
    print("\nAvailable models:")
    for k, v in MODELS.items():
        print(f"  [{k}] {v['name']} ({v['slug']})")

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ("models", "m"):
            show_models(); return
        if sys.argv[1] in ("chat", "c") and len(sys.argv) > 3:
            model = sys.argv[2] if any(sys.argv[2] == v["slug"] for v in MODELS.values()) else "gpt-5-5"
            prompt = " ".join(sys.argv[3:])
            client = ChatGPT()
            print(f"[{model}] ", end="", flush=True)
            reply, _ = client.chat(prompt, model=model, stream=True, first=True)
            print(f"\n{reply}"); return

    show_models()
    print("\nSelect model number (default 1): ", end="")
    choice = input().strip()
    model = MODELS.get(choice, {}).get("slug", "gpt-5-5")
    client = ChatGPT()
    print(f"\nChat started (model: {model}, device: {client.device_id[:8]}...)\n")
    first = True
    while True:
        try: msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt): print(); break
        if not msg: continue
        if msg.lower() in ("exit", "quit", "bye"): break
        print("GPT: ", end="", flush=True)
        reply, _ = client.chat(msg, model=model, stream=True, first=first)
        first = False
        if not reply: print("[empty]")
        print()
if __name__ == "__main__":
    main()
import json, uuid, sys
import requests

BASE_URL = "https://android.chat.openai.com"
UA = "ChatGPT/1.2026.195 (Android 16; 2412DPC0AG; build 2619512)"

def fetch_models():
    try:
        s = requests.Session()
        s.headers.update({"accept": "application/json", "oai-client-type": "android",
                          "oai-package-name": "com.openai.chatgpt", "user-agent": UA})
        r = s.get(f"{BASE_URL}/backend-anon/models", params={"iim": "false", "supports_model_picker_upgrade_presets": "true"}, timeout=10)
        if r.status_code == 200:
            models = r.json().get("models", [])
            if models:
                return {str(i): {"slug": m["slug"], "name": m.get("title", m["slug"])} for i, m in enumerate(models, 1)}
    except Exception:
        pass
    return {"1": {"slug": "gpt-5-5", "name": "GPT-5.5"}, "2": {"slug": "gpt-5-3", "name": "GPT-5.3"},
            "3": {"slug": "gpt-5-mini", "name": "GPT-5-mini"}, "4": {"slug": "auto", "name": "Auto"}}

MODELS = fetch_models()

def parse_sse(chunks, on_delta=None):
    buf, events = "", []
    for chunk in chunks:
        buf += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            lines = block.strip().split("\n")
            evt_type, data_lines = "message", []
            for line in lines:
                if line.startswith("event: "): evt_type = line[7:].strip()
                elif line.startswith("data: "): data_lines.append(line[6:])
            if not data_lines: continue
            raw = "\n".join(data_lines)
            try: parsed = json.loads(raw)
            except json.JSONDecodeError: parsed = raw
            events.append((evt_type, parsed))
            if on_delta and evt_type == "delta":
                on_delta(parsed)
    return events

def extract_reply(events):
    parts, asst_msg = [], None
    for evt_type, d in events:
        if evt_type != "delta": continue
        if isinstance(d, str): parts.append(d); continue
        if not isinstance(d, dict): continue
        v = d.get("v")
        if isinstance(v, str): parts.append(v); continue
        if d.get("o") == "patch" and isinstance(v, list):
            for p in v:
                if isinstance(p, dict) and p.get("o") == "append" and "/parts/" in p.get("p", "") and isinstance(p.get("v"), str) and p["v"].strip():
                    parts.append(p["v"])
            continue
        if isinstance(v, dict) and d.get("o") != "patch":
            m = v.get("message", {})
            if isinstance(m, dict) and m.get("author", {}).get("role") in ("assistant", "system") and m.get("id"):
                ct = m.get("content", {}).get("content_type")
                if ct: asst_msg = m
    reply = "".join(parts)
    if asst_msg:
        ct = asst_msg.get("content", {})
        existing = ct.get("parts", [])
        if not any(p for p in existing if isinstance(p, str) and p.strip()):
            ct = {"content_type": "text", "parts": [reply] if reply else []}
        return reply, {
            "id": asst_msg["id"], "author": {"role": "assistant"},
            "content": ct,
            "status": "finished_successfully", "recipient": "all",
            "metadata": asst_msg.get("metadata", {}),
        }
    return reply, None

def stream_printer(d):
    if isinstance(d, str) and d.strip(): print(d, end="", flush=True); return
    if not isinstance(d, dict): return
    v = d.get("v")
    if isinstance(v, str) and v.strip(): print(v, end="", flush=True); return
    if d.get("o") == "patch" and isinstance(v, list):
        for p in v:
            if isinstance(p, dict) and p.get("o") == "append" and "/parts/" in p.get("p", "") and isinstance(p.get("v"), str) and p["v"].strip():
                print(p["v"], end="", flush=True)

def _base_body(model):
    return {"action": "next", "model": model, "history_and_training_disabled": False,
            "fork_from_shared_post": False, "enable_message_followups": False,
            "force_use_sse": False, "force_use_search": None, "force_paragen": False,
            "supported_encodings": ["v1"], "supports_buffering": True,
            "timezone": "Asia/Baghdad", "timezone_offset_min": -180,
            "system_hints": [], "is_onboarding_conversation": False,
            "no_auth_ad_preferences": {"personalization_enabled": True, "history_enabled": True}}

class ChatGPT:
    def __init__(self):
        self.device_id = str(uuid.uuid4())
        self.sess = requests.Session()
        self.sess.headers.update({"accept": "application/json", "accept-encoding": "gzip",
            "accept-language": "en-US,en;q=0.9", "cache-control": "no-cache",
            "content-type": "application/json", "chatgpt-account-id": "default",
            "chatgpt-residency-region": "no_constraint", "oai-client-type": "android",
            "oai-device-id": self.device_id, "oai-package-name": "com.openai.chatgpt",
            "user-agent": UA, "x-device-tier": "upper_mid"})
        self.conduit_token = self.conversation_id = self.parent_id = None
        self.history = []

    def _post(self, path, body=None):
        hdrs = {"x-openai-target-path": path}
        if self.conduit_token and "sentinel" not in path:
            hdrs["x-conduit-token"] = self.conduit_token
        r = self.sess.post(f"{BASE_URL}{path}", json=body or {}, headers=hdrs, timeout=60)
        r.raise_for_status()
        return r.json()

    def _stream(self, path, body):
        hdrs = {"x-openai-target-path": path}
        if self.conduit_token:
            hdrs["x-conduit-token"] = self.conduit_token
        return self.sess.post(f"{BASE_URL}{path}", json=body, headers=hdrs, stream=True, timeout=120)

    def chat(self, text, model="gpt-5-5", stream=False, first=False):
        if first:
            self.history = []
            self.parent_id = str(uuid.uuid4())
            self.conversation_id = str(uuid.uuid4())
            self._post("/backend-anon/sentinel/chat-requirements")
            self._post("/backend-anon/conversation/init", {})

        prep = _base_body(model) | {"conversation_id": self.conversation_id,
                                    "parent_message_id": self.parent_id,
                                    "client_prepare_dispatch": "debounced",
                                    "client_prepare_source": "composer_editor_state"}
        self.conduit_token = self._post("/backend-anon/f/conversation/prepare", prep)["conduit_token"]

        msg_id = str(uuid.uuid4())
        user_msg = {"id": msg_id, "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [text]},
                    "status": "finished_successfully", "recipient": "all",
                    "metadata": {"model_slug": model, "default_model_slug": model,
                        "is_visually_hidden_from_conversation": False,
                        "exclude_after_next_user_message": False, "content_references": [],
                        "search_result_groups": [], "search_queries": [], "image_results": [],
                        "dictation": False, "voice_mode_message": False, "image_gen_async": False,
                        "trigger_async_ux": False, "writing_blocks": {}}}
        self.history.append(user_msg)

        body = _base_body(model) | {"messages": list(self.history), "enable_message_followups": True,
                                    "force_use_sse": True, "client_prepare_state": "success", "stream": True}
        r = self._stream("/backend-anon/f/conversation", body)
        events = parse_sse(r.iter_content(chunk_size=None), on_delta=stream_printer if stream else None)
        if stream: print()

        reply, asst = extract_reply(events)
        if asst: self.history.append(asst)
        return reply, self.conversation_id

def show_models():
    print("\nAvailable models:")
    for k, v in MODELS.items():
        print(f"  [{k}] {v['name']} ({v['slug']})")

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ("models", "m"):
            show_models(); return
        if sys.argv[1] in ("chat", "c") and len(sys.argv) > 3:
            model = sys.argv[2] if any(sys.argv[2] == v["slug"] for v in MODELS.values()) else "gpt-5-5"
            prompt = " ".join(sys.argv[3:])
            client = ChatGPT()
            print(f"[{model}] ", end="", flush=True)
            reply, _ = client.chat(prompt, model=model, stream=True, first=True)
            print(f"\n{reply}"); return

    show_models()
    print("\nSelect model number (default 1): ", end="")
    choice = input().strip()
    model = MODELS.get(choice, {}).get("slug", "gpt-5-5")
    client = ChatGPT()
    print(f"\nChat started (model: {model}, device: {client.device_id[:8]}...)\n")
    first = True
    while True:
        try: msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt): print(); break
        if not msg: continue
        if msg.lower() in ("exit", "quit", "bye"): break
        print("GPT: ", end="", flush=True)
        reply, _ = client.chat(msg, model=model, stream=True, first=first)
        first = False
        if not reply: print("[empty]")
        print()

if __name__ == "__main__":
    main()
from flask import Flask, render_template_string, request, jsonify
from gpt import ChatGPT, MODELS

app = Flask(__name__)
client = ChatGPT()
first_turn = True

HTML_CODE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تطبيق الذكاء الاصطناعي</title>
    <style>
        body { font-family: sans-serif; background-color: #121212; color: white; margin: 0; padding: 15px; }
        .container { max-width: 500px; margin: auto; }
        select, input, button { width: 100%; padding: 12px; margin-top: 8px; border-radius: 8px; border: none; font-size: 16px; box-sizing: border-box; }
        select { background-color: #2c2c2c; color: white; }
        #chatbox { height: 60vh; overflow-y: auto; background: #1e1e1e; padding: 10px; border-radius: 8px; margin-top: 10px; }
        .msg { margin-bottom: 10px; padding: 8px 12px; border-radius: 8px; max-width: 80%; }
        .user { background: #007bff; float: left; clear: both; }
        .bot { background: #333; float: right; clear: both; }
        .input-group { display: flex; gap: 5px; margin-top: 10px; }
        .input-group input { flex: 1; }
        .input-group button { width: 80px; background: #28a745; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h3>تطبيق الذكاء الاصطناعي</h3>
        <select id="model">
            {% for k, v in models.items() %}
                <option value="{{ v.slug }}">{{ v.name }}</option>
            {% endfor %}
        </select>
        <div id="chatbox"></div>
        <div class="input-group">
            <input type="text" id="userInput" placeholder="اكتب رسالتك...">
            <button onclick="sendMsg()">إرسال</button>
        </div>
    </div>

    <script>
        async function sendMsg() {
            let input = document.getElementById("userInput");
            let model = document.getElementById("model").value;
            let text = input.value.trim();
            if(!text) return;

            let chatbox = document.getElementById("chatbox");
            chatbox.innerHTML += `<div class="msg user">${text}</div>`;
            input.value = "";

            let res = await fetch("/chat", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({prompt: text, model: model})
            });
            let data = await res.json();
            chatbox.innerHTML += `<div class="msg bot">${data.reply}</div>`;
            chatbox.scrollTop = chatbox.scrollHeight;
        }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_CODE, models=MODELS)

@app.route("/chat", methods=["POST"])
def chat():
    global first_turn
    data = request.json
    prompt = data.get("prompt")
    model = data.get("model", "gpt-5-5")
    reply, _ = client.chat(prompt, model=model, stream=False, first=first_turn)
    first_turn = False
    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)