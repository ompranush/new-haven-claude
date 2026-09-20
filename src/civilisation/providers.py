"""LLM backends. Every backend answers one question: system + user prompt + JSON schema -> dict.

Claude uses the native Anthropic SDK (structured outputs). Everything else goes through
the OpenAI-compatible chat API, which OpenAI, xAI (Grok), Google Gemini, Mistral, Groq,
OpenRouter and a local Ollama all expose. Keys are held in memory only.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Optional

PROVIDERS = {
    # name: (base_url or None for native, default model, key env var, notes)
    "anthropic": (None, "claude-opus-5", "ANTHROPIC_API_KEY", "Claude — native SDK, structured JSON output"),
    "openai": ("https://api.openai.com/v1", "gpt-5", "OPENAI_API_KEY", "ChatGPT models"),
    "xai": ("https://api.x.ai/v1", "grok-4", "XAI_API_KEY", "Grok"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash", "GEMINI_API_KEY", "Google Gemini via its OpenAI-compatible endpoint"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-large-latest", "MISTRAL_API_KEY", "Mistral"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY", "Groq (fast open models)"),
    "openrouter": ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5", "OPENROUTER_API_KEY", "OpenRouter (any model)"),
    "ollama": ("http://localhost:11434/v1", "llama3.1", "", "Local Ollama — free, no key needed"),
    "custom": ("", "", "", "Any OpenAI-compatible endpoint: set base URL and model"),
}

# rough $ per million tokens (input, output) for the cost readout; unknown models fall back to a guess
PRICES = {"claude-opus-5": (5, 25), "claude-sonnet-5": (2, 10), "claude-haiku-4-5": (1, 5), "gpt-5": (1.25, 10), "gpt-5-mini": (0.25, 2),
          "gpt-4o": (2.5, 10), "gpt-4o-mini": (0.15, 0.6), "grok-4": (3, 15), "grok-3-mini": (0.3, 0.5), "gemini-2.5-pro": (1.25, 10),
          "gemini-2.5-flash": (0.3, 2.5), "mistral-large-latest": (2, 6), "llama-3.3-70b-versatile": (0.6, 0.8)}


class BackendError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0


class Backend:
    provider: str = ""
    model: str = ""

    def json_call(self, system: str, user: str, schema: dict, max_tokens: int = 1024, effort: str = "low") -> tuple[dict, Usage]:
        raise NotImplementedError

    def text_call(self, system: str, user: str, max_tokens: int = 4000) -> str:
        raise NotImplementedError

    def ping(self) -> str:
        """Cheap liveness check; returns a human-readable success line or raises."""
        data, _ = self.json_call("Reply with JSON.", "Return {\"ok\": true}.",
                                 {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}, max_tokens=64)
        return f"{self.provider}/{self.model} answered."

    def price(self):
        return PRICES.get(self.model, (2.0, 8.0))


class AnthropicBackend(Backend):
    provider = "anthropic"

    def __init__(self, model: str = "claude-opus-5", api_key: Optional[str] = None):
        import anthropic
        self._mod = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    def json_call(self, system, user, schema, max_tokens=1024, effort="low"):
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except self._mod.APIError as e:
            from .security import scrub
            raise BackendError(scrub(f"{type(e).__name__}: {e}")) from e
        if resp.stop_reason == "refusal":
            raise BackendError("refused")
        u = Usage(resp.usage.input_tokens, resp.usage.output_tokens, getattr(resp.usage, "cache_read_input_tokens", 0) or 0)
        return json.loads(next(b.text for b in resp.content if b.type == "text")), u

    def text_call(self, system, user, max_tokens=4000):
        with self.client.messages.stream(model=self.model, max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": user}]) as stream:
            msg = stream.get_final_message()
        return "".join(b.text for b in msg.content if b.type == "text")


class OpenAICompatibleBackend(Backend):
    """OpenAI, xAI, Gemini, Mistral, Groq, OpenRouter, Ollama, or any custom base_url."""

    def __init__(self, provider: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        import openai
        from .security import allow_custom_providers, check_base_url
        self._mod = openai
        self.provider = provider
        self.model = model
        if provider in ("custom", "ollama") and not allow_custom_providers():
            raise BackendError("custom and local providers are disabled on this server (ALLOW_CUSTOM_PROVIDERS)")
        if provider == "custom":
            base_url = check_base_url(base_url or "")
        elif base_url and base_url != PROVIDERS.get(provider, ("", "", "", ""))[0]:
            raise BackendError("base URL can only be set for the custom provider")
        url = base_url or PROVIDERS.get(provider, ("", "", "", ""))[0] or None
        self.client = openai.OpenAI(api_key=api_key or ("ollama" if provider == "ollama" else None), base_url=url)

    def json_call(self, system, user, schema, max_tokens=1024, effort="low"):
        # json_object mode is the widest-supported contract; the schema is spelled out in the prompt and validated after
        sys_prompt = system + "\n\nRespond with a single JSON object matching this JSON schema exactly, and nothing else:\n" + json.dumps(schema)
        try:
            resp = self.client.chat.completions.create(
                model=self.model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
            )
        except self._mod.APIError as e:
            from .security import scrub
            raise BackendError(scrub(f"{type(e).__name__}: {e}")) from e
        text = resp.choices[0].message.content or ""
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise BackendError(f"model returned invalid JSON: {text[:120]}") from e
        for k in schema.get("required", []):
            if k not in data:
                raise BackendError(f"model omitted '{k}'")
        u = resp.usage
        return data, Usage(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0, 0)

    def text_call(self, system, user, max_tokens=4000):
        resp = self.client.chat.completions.create(model=self.model, max_tokens=max_tokens,
                                                   messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""


def make_backend(provider: str, model: str = "", api_key: Optional[str] = None, base_url: Optional[str] = None) -> Backend:
    provider = (provider or "anthropic").lower()
    model = model or PROVIDERS.get(provider, ("", "", "", ""))[1]
    if provider == "anthropic":
        return AnthropicBackend(model=model, api_key=api_key)
    if provider not in PROVIDERS:
        raise BackendError(f"unknown provider {provider!r}")
    return OpenAICompatibleBackend(provider, model, api_key=api_key, base_url=base_url)
