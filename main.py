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
