import os
import random
import time
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
import requests

from .text_chunker import chunk_text


class LLMFallback:
    PROVIDERS = ("gemini", "groq", "deepseek")

    def __init__(self, timeout: float = 30.0, max_chunk_chars: int = 12000):
        load_dotenv(Path.cwd() / ".env")
        self.timeout = timeout
        self.max_chunk_chars = max_chunk_chars
        self.events: list[dict] = []

    def _gemini(self, prompt: str) -> str:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        response = requests.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                 json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": prompt}]},
                                 timeout=self.timeout)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _groq(self, prompt: str) -> str:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not configured")
        response = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                 json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}]},
                                 timeout=self.timeout)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _deepseek(self, prompt: str) -> str:
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        response = requests.post("https://api.deepseek.com/chat/completions",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                 json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]},
                                 timeout=self.timeout)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def generate(self, prompt: str, max_attempts_per_provider: int = 3) -> dict:
        functions: dict[str, Callable[[str], str]] = {
            "gemini": self._gemini,
            "groq": self._groq,
            "deepseek": self._deepseek,
        }
        chunks_output: list[str] = []
        overlap = min(200, max(0, self.max_chunk_chars // 10))
        for chunk_index, chunk in enumerate(chunk_text(prompt, self.max_chunk_chars, overlap)):
            for provider in self.PROVIDERS:
                for attempt in range(max_attempts_per_provider):
                    try:
                        output = functions[provider](chunk)
                        self.events.append({"provider": provider, "chunk": chunk_index, "attempt": attempt + 1, "status": "success"})
                        chunks_output.append(output)
                        break
                    except requests.HTTPError as error:
                        status = error.response.status_code if error.response is not None else None
                        self.events.append({"provider": provider, "chunk": chunk_index, "attempt": attempt + 1, "status": "http_error", "httpStatus": status})
                        if status == 413:
                            smaller_chunks = chunk_text(chunk, max(200, self.max_chunk_chars // 2), 100)
                            self.events.append({"provider": provider, "chunk": chunk_index, "status": "chunked", "chunkCount": len(smaller_chunks)})
                            smaller_output: list[str] = []
                            for smaller_index, smaller in enumerate(smaller_chunks):
                                try:
                                    smaller_output.append(functions[provider](smaller))
                                    self.events.append({
                                        "provider": provider,
                                        "chunk": chunk_index,
                                        "subChunk": smaller_index,
                                        "attempt": attempt + 1,
                                        "status": "success",
                                    })
                                except Exception:
                                    smaller_output = []
                                    break
                            if smaller_output:
                                chunks_output.append("".join(smaller_output))
                                break
                            break
                        if status == 429:
                            delay = min(60.0, (2 ** attempt) + random.uniform(0.0, 1.0))
                            time.sleep(delay)
                            continue
                        break
                    except (requests.Timeout, requests.ConnectionError, RuntimeError) as error:
                        self.events.append({"provider": provider, "chunk": chunk_index, "attempt": attempt + 1, "status": "failure", "error": str(error)})
                        break
                if chunks_output and len(chunks_output) > chunk_index:
                    break
            if not (chunks_output and len(chunks_output) > chunk_index):
                continue
        if chunks_output:
            providers_used = [event["provider"] for event in self.events if event["status"] == "success"]
            return {"provider": providers_used[-1] if providers_used else None, "chunks": chunks_output, "success": True, "events": list(self.events)}
        return {"provider": None, "chunks": [], "success": False, "events": list(self.events)}