"""
Helpers for translating between Ollama and LM Studio / OpenAI model formats.
"""

from __future__ import annotations

import time


# Architectures with confirmed tool-calling support
_TOOL_ARCHS: frozenset[str] = frozenset({
    "qwen2", "qwen3", "llama", "mistral", "phi3", "phi", "gemma3", "command-r",
    "deepseek", "hermes", "functionary",
})


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def capabilities_from_lms(lms_type: str, arch: str = "", model_id: str = "") -> list[str]:
    """
    Derive Ollama capability strings from LM Studio model metadata.

    Args:
        lms_type:  LM Studio model type field (e.g. "llm", "vlm", "embeddings").
        arch:      Architecture string from /api/v0/models (e.g. "llama").
        model_id:  Model identifier, used as a fallback arch hint.

    Returns:
        List of Ollama capability strings.
    """
    if lms_type == "embeddings":
        return ["embedding"]

    caps: list[str] = ["completion"]

    if lms_type == "vlm":
        caps.append("vision")

    arch_key = arch.lower().replace("-", "").replace("_", "")
    id_key = model_id.lower()
    if any(a in arch_key or a in id_key for a in _TOOL_ARCHS):
        caps.append("tools")

    return caps


def lms_v0_to_ollama_model(v0: dict) -> dict:
    """Build a rich Ollama model dict from a /api/v0/models entry."""
    model_id: str = v0["id"]
    arch: str = v0.get("arch", "llama")
    quant: str = v0.get("quantization", "unknown")
    compat: str = v0.get("compatibility_type", "gguf")
    return {
        "name": model_id,
        "model": model_id,
        "modified_at": now_iso(),
        "size": 0,
        "digest": "",
        "details": {
            "format": compat,
            "family": arch,
            "families": [arch],
            "parameter_size": "unknown",
            "quantization_level": quant,
        },
    }


def openai_model_to_ollama(model_id: str) -> dict:
    """
    Minimal Ollama model dict used as a fallback when /api/v0/models metadata
    is unavailable for a given model ID.
    """
    return {
        "name": model_id,
        "model": model_id,
        "modified_at": now_iso(),
        "size": 0,
        "digest": "",
        "details": {
            "format": "gguf",
            "family": "llama",
            "families": ["llama"],
            "parameter_size": "unknown",
            "quantization_level": "unknown",
        },
    }


# Mapping of Ollama generation options → OpenAI parameter names
OPTION_MAP: dict[str, str] = {
    "temperature": "temperature",
    "top_p": "top_p",
    "seed": "seed",
    "num_predict": "max_tokens",
    "stop": "stop",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
}
