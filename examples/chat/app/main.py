"""Chat with a language model, its reply streaming in as it is written.

Any server speaking the OpenAI chat completions API works: OpenAI, Ollama, LM
Studio, llama.cpp, vLLM. The defaults reach Ollama on the computer the phone is
plugged into, after ``adb reverse tcp:11434 tcp:11434``; a debug build may use
plain HTTP to localhost, a release build only HTTPS.
"""

import json

import httpx

import pycompose.blocks as pc

URL = "http://localhost:11434/v1/chat/completions"
MODEL = "llama3.2"
KEY = ""  # a bearer token, for a server that needs one


def reply(message: str, history: list[dict[str, str]]):
    """Stream the model's reply to the conversation so far."""
    messages = [*history, {"role": "user", "content": message}]
    headers = {"Authorization": f"Bearer {KEY}"} if KEY else {}
    body = {"model": MODEL, "messages": messages, "stream": True}
    text = ""
    with httpx.stream("POST", URL, json=body, headers=headers, timeout=60) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                text += json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
                yield text


app = pc.ChatInterface(reply)
