const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const messagesElement = document.getElementById("messages");
const sendButton = document.getElementById("send-button");
const connectionDot = document.getElementById("connection-dot");
const connectionLabel = document.getElementById("connection-label");
const newChatButton = document.getElementById("new-chat");

const conversation = [];
let isSending = false;

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `message-row ${role}`;

  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "assistant-avatar message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "c.";
    row.append(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = text;
  row.append(bubble);
  messagesElement.append(row);
  row.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return row;
}

function setConnection(connected, message) {
  connectionDot.classList.toggle("connected", connected);
  connectionDot.classList.toggle("disconnected", !connected);
  connectionLabel.textContent = message;
}

async function checkConnection() {
  try {
    const response = await fetch("/api/health");
    const result = await response.json();
    setConnection(result.ok, result.ok ? "Ollama connected" : result.error);
  } catch (error) {
    setConnection(false, "Can't reach the local app server");
  }
}

function setSending(sending) {
  isSending = sending;
  sendButton.disabled = sending;
  input.disabled = sending;
  sendButton.querySelector("span:first-child").textContent = sending ? "Thinking" : "Send";
}

async function sendMessage(text) {
  const content = text.trim();
  if (!content || isSending) return;

  const welcome = messagesElement.querySelector(".welcome-message");
  if (welcome) welcome.remove();

  conversation.push({ role: "user", content });
  addMessage("user", content);
  input.value = "";
  input.style.height = "auto";
  setSending(true);
  const pending = addMessage("assistant", "Thinking through your space…");
  pending.querySelector(".message-bubble").classList.add("pending");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conversation }),
    });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || `Request failed (${response.status}).`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("Your browser could not read the streamed response.");

    const decoder = new TextDecoder();
    let buffer = "";
    let reply = "";
    const bubble = pending.querySelector(".message-bubble");

    function readChunk(line) {
      if (!line.trim()) return;
      const chunk = JSON.parse(line);
      if (chunk.error) throw new Error(chunk.error);
      if (typeof chunk.message?.content === "string") {
        reply += chunk.message.content;
        bubble.textContent = reply;
        bubble.classList.remove("pending");
        pending.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) readChunk(line);
      if (done) break;
    }
    if (buffer.trim()) readChunk(buffer);
    if (!reply.trim()) throw new Error("Ollama returned an empty response.");

    conversation.push({ role: "assistant", content: reply });
    setConnection(true, "Ollama connected");
  } catch (error) {
    pending.remove();
    conversation.pop();
    addMessage("assistant", `I couldn't get a response. ${error.message}`);
    setConnection(false, "Ollama unavailable");
  } finally {
    setSending(false);
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

messagesElement.addEventListener("click", (event) => {
  const chip = event.target.closest(".suggestion-chip");
  if (chip) sendMessage(chip.dataset.prompt);
});

newChatButton.addEventListener("click", () => {
  if (isSending) return;
  conversation.length = 0;
  messagesElement.replaceChildren();
  const welcome = document.createElement("div");
  welcome.className = "welcome-message";
  welcome.innerHTML = `
    <span class="welcome-sparkle" aria-hidden="true">✳</span>
    <h3>Let's make your home work beautifully.</h3>
    <p>Share your room sizes and what matters most. I'll help you plan a cohesive home with furniture that fits, useful storage, layered lighting and realistic walkways.</p>
    <div class="suggestion-label">A good place to start</div>
    <button class="suggestion-chip" type="button" data-prompt="Help me plan my home. Ask me for the essential details you need, one concise set of questions at a time.">What details should I share?</button>`;
  messagesElement.append(welcome);
  input.focus();
});

checkConnection();
