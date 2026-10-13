"""Provider-agnostic LLM client (Groq or Gemini via their OpenAI-compatible APIs).

- Retries short rate limits (requests or tokens per minute) with exponential backoff.
- Fails fast on daily quota errors, because waiting seconds will not reset a daily limit.
- Optional fallback: when the primary provider is out of quota, switch to the other
  provider, and try the primary again after a cool-down. The app enables this; the
  evaluation keeps it off so every result comes from one model.
"""
import os
import time

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

load_dotenv()

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "openai/gpt-oss-120b",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-flash-latest",
    },
}

DAILY_LIMIT_MARKERS = ("per day", "tokens per day", "requests per day", "tpd", "rpd",
                       "quota", "resource_exhausted", "exceeded your current quota")
PRIMARY_RETRY_AFTER_S = 600   # after a fallback, try the primary provider again after 10 min


class QuotaExhausted(Exception):
    """The provider cannot serve requests right now (daily limit or retries used up)."""


def _get_key(name: str) -> str | None:
    """Read a key from the environment, or from Streamlit secrets when deployed."""
    value = os.getenv(name)
    if not value:
        try:
            import streamlit as st
            value = st.secrets.get(name)
        except Exception:
            value = None
    if value and not value.startswith("paste_"):
        return value
    return None


class _Backend:
    def __init__(self, provider: str):
        cfg = PROVIDERS[provider]
        self.provider = provider
        self.model = os.getenv(cfg["model_env"]) or _get_key(cfg["model_env"]) or cfg["default_model"]
        self.client = OpenAI(api_key=_get_key(cfg["key_env"]), base_url=cfg["base_url"])


class LLMClient:
    def __init__(self, provider: str | None = None, allow_fallback: bool = False):
        primary = (provider or os.getenv("LLM_PROVIDER") or _get_key("LLM_PROVIDER") or "groq").lower()
        if primary not in PROVIDERS:
            raise ValueError(f"Unknown LLM_PROVIDER '{primary}'. Use one of {list(PROVIDERS)}")
        order = [primary] + ([p for p in PROVIDERS if p != primary] if allow_fallback else [])
        self.backends = [_Backend(p) for p in order if _get_key(PROVIDERS[p]["key_env"])]
        if not self.backends or self.backends[0].provider != primary:
            raise ValueError(f"Missing {PROVIDERS[primary]['key_env']} in .env")
        self.active = 0
        self._switched_at = 0.0

    @property
    def provider(self) -> str:
        return self.backends[self.active].provider

    @property
    def model(self) -> str:
        return self.backends[self.active].model

    def _chat_once(self, be: _Backend, messages: list[dict], temperature: float,
                   max_tokens: int, max_retries: int) -> str:
        extra = {"reasoning_effort": "low"}
        for attempt in range(max_retries):
            try:
                resp = be.client.chat.completions.create(
                    model=be.model, messages=messages,
                    temperature=temperature, max_tokens=max_tokens, **extra)
                return (resp.choices[0].message.content or "").strip()
            except RateLimitError as e:
                if any(m in str(e).lower() for m in DAILY_LIMIT_MARKERS):
                    raise QuotaExhausted(f"{be.provider} daily quota reached") from e
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                print(f"[llm] {be.provider} rate limit, retrying in {wait}s...")
                time.sleep(wait)
            except APIConnectionError:
                time.sleep(3)
            except APIStatusError as e:
                if e.status_code >= 500 and attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                raise
        raise QuotaExhausted(f"{be.provider} still rate limited after {max_retries} tries")

    def chat(self, messages: list[dict], temperature: float = 0.0,
             max_tokens: int = 1024, max_retries: int = 3) -> str:
        """Send messages and return the reply text, falling back between providers if allowed."""
        if self.active > 0 and time.time() - self._switched_at > PRIMARY_RETRY_AFTER_S:
            self.active = 0   # give the primary provider another chance
        last_error = None
        while self.active < len(self.backends):
            try:
                return self._chat_once(self.backends[self.active], messages,
                                       temperature, max_tokens, max_retries)
            except QuotaExhausted as e:
                last_error = e
                print(f"[llm] {e}")
                if self.active + 1 >= len(self.backends):
                    break
                self.active += 1
                self._switched_at = time.time()
                print(f"[llm] switching to fallback provider: {self.provider}")
        self.active = 0
        raise RuntimeError(f"The free AI quota is used up for now ({last_error}). "
                           "Please try again later.")


if __name__ == "__main__":
    llm = LLMClient(allow_fallback=True)
    print("Configured providers:", [b.provider for b in llm.backends])
    t0 = time.time()
    answer = llm.chat([{"role": "user",
                        "content": "Write a SQLite query that counts rows in a table named orders. Return only SQL."}])
    print(f"Provider: {llm.provider} | Model: {llm.model} | {time.time()-t0:.1f}s")
    print(answer)