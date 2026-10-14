# Casa — Interior Design Assistant

A local interior-design chatbot powered by Ollama and `qwen3:4b`. It asks for missing room
dimensions and design requirements, then helps create practical room-by-room proposals.
Your chat runs on your computer; no API key or third-party AI service is used.

## Start the app

1. Make sure Ollama is running and `ollama list` includes `qwen3:4b`.
2. Double-click `start.bat` in this folder. Python 3 is required; the app uses only Python's
   standard library.
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.
4. Keep the command window open while chatting. Press Ctrl+C in it to stop the app.

The server connects to Ollama at `http://127.0.0.1:11434` and uses the `qwen3:4b` model.
Replies stream into the chat as they are generated; the app filters Qwen's internal
`<think>` reasoning so only its answer is displayed.
