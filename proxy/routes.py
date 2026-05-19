"""
FastAPI application and all route handlers for the Ollama → LM Studio proxy.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import (
    CONNECT_TIMEOUT,
    LM_STUDIO_BASE,
    LMS_API_KEY,
    LISTEN_HOST,
    LISTEN_PORT,
    OLLAMA_VERSION,
    REQUEST_TIMEOUT,
)
from .models import (
    OPTION_MAP,
    capabilities_from_lms,
    lms_v0_to_ollama_model,
    now_iso,
    openai_model_to_ollama,
)

log = logging.getLogger("ollama-proxy")

# ── Shared async HTTP client ──────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise HTTPException(503, "Proxy client not initialised yet.")
    return _client


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _client
    timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
    default_headers = {"Authorization": f"Bearer {LMS_API_KEY}"} if LMS_API_KEY else {}
    _client = httpx.AsyncClient(base_url=LM_STUDIO_BASE, timeout=timeout, headers=default_headers)
    auth_status = "key configured" if LMS_API_KEY else "no auth"
    log.info("Proxy listening on %s:%d  →  %s  (%s)", LISTEN_HOST, LISTEN_PORT, LM_STUDIO_BASE, auth_status)
    yield
    await _client.aclose()
    log.info("Proxy shut down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Ollama → LM Studio Proxy", lifespan=_lifespan)


# ── Middleware: log every request ─────────────────────────────────────────────

@app.middleware("http")
async def _log_requests(request: Request, call_next):
    body_bytes = await request.body()
    preview = body_bytes.decode(errors="replace")[:300] if body_bytes else ""
    log.info("→ %s %s  body=%s", request.method, request.url.path, preview or "(none)")

    async def _receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    request = Request(request.scope, _receive)
    response = await call_next(request)
    log.info("← %s %s  status=%d", request.method, request.url.path, response.status_code)
    return response


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_v0_models_map() -> dict[str, dict]:
    """
    Fetch LM Studio's /api/v0/models (extended inventory) and return a dict
    keyed by model ID.  Returns an empty dict on any error so callers degrade
    gracefully rather than failing hard.
    """
    try:
        resp = await _get_client().get("api/v0/models")
        resp.raise_for_status()
        return {item["id"]: item for item in resp.json().get("data", [])}
    except Exception as exc:
        log.debug("Could not fetch /api/v0/models: %s", exc)
        return {}


async def _stream_ollama_chunks(openai_payload: dict) -> AsyncIterator[bytes]:
    """
    Open a streaming POST to LM Studio's /v1/chat/completions, consume each
    SSE line, and re-emit it as a newline-delimited Ollama streaming chunk.
    """
    model: str = openai_payload.get("model", "")

    try:
        async with _get_client().stream(
            "POST", "v1/chat/completions", json=openai_payload
        ) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                if not raw_line.startswith("data:"):
                    continue

                payload = raw_line[5:].strip()

                if payload == "[DONE]":
                    terminal = {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": ""},
                        "done": True,
                        "done_reason": "stop",
                    }
                    yield (json.dumps(terminal) + "\n").encode()
                    return

                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                content: str = delta.get("content", "")
                finish: str | None = choice.get("finish_reason")

                ollama_chunk: dict = {
                    "model": model,
                    "created_at": now_iso(),
                    "message": {"role": "assistant", "content": content},
                    "done": finish is not None,
                }
                if finish is not None:
                    ollama_chunk["done_reason"] = finish

                yield (json.dumps(ollama_chunk) + "\n").encode()

    except httpx.ConnectError:
        yield (json.dumps({"error": "LM Studio server is not reachable.", "done": True}) + "\n").encode()
    except httpx.HTTPStatusError as exc:
        yield (
            json.dumps({"error": f"LM Studio returned HTTP {exc.response.status_code}", "done": True}) + "\n"
        ).encode()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/version")
async def get_version() -> JSONResponse:
    """Ollama version handshake — clients check this before sending real requests."""
    return JSONResponse({"version": OLLAMA_VERSION})


@app.get("/api/tags")
async def get_tags() -> JSONResponse:
    """
    Enumerate loaded models from LM Studio and return them in Ollama's
    /api/tags format.  Enriches each entry with arch/quantization metadata
    from LM Studio's /api/v0/models when available.
    """
    client = _get_client()
    try:
        resp = await client.get("v1/models")
        resp.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(502, "LM Studio server is not reachable. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "LM Studio did not respond in time.")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"LM Studio returned {exc.response.status_code}")

    loaded_ids: list[str] = [item["id"] for item in resp.json().get("data", [])]
    if not loaded_ids:
        log.warning("No models currently loaded in LM Studio.")

    v0_map = await _fetch_v0_models_map()
    models = [
        lms_v0_to_ollama_model(v0_map[mid]) if mid in v0_map else openai_model_to_ollama(mid)
        for mid in loaded_ids
    ]
    return JSONResponse({"models": models})


@app.post("/api/show", response_model=None)
async def show_model(request: Request) -> JSONResponse:
    """
    Return synthetic Ollama-format model detail for a given model name.
    Called by clients (e.g. VS Code) before opening a chat session.
    """
    body: dict = await request.json()
    model: str = body.get("name") or body.get("model", "")

    client = _get_client()
    try:
        resp = await client.get(f"v1/models/{model}")
        resp.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(502, "LM Studio server is not reachable. Is it running?")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, f"Model '{model}' is not currently loaded in LM Studio.")
        raise HTTPException(502, f"LM Studio returned {exc.response.status_code}")

    v0_map = await _fetch_v0_models_map()
    v0 = v0_map.get(model, {})

    lms_type: str = v0.get("type", "llm")
    arch: str = v0.get("arch", "llama")
    quant: str = v0.get("quantization", "unknown")
    compat: str = v0.get("compatibility_type", "gguf")
    ctx_len: int = v0.get("max_context_length", 0)

    capabilities = capabilities_from_lms(lms_type, arch, model)

    payload: dict = {
        "model": model,
        "modelfile": f"FROM {model}",
        "parameters": "",
        "template": "{{ .Prompt }}",
        "capabilities": capabilities,
        "details": {
            "parent_model": "",
            "format": compat,
            "family": arch,
            "families": [arch],
            "parameter_size": "unknown",
            "quantization_level": quant,
        },
        "model_info": {
            "general.architecture": arch,
            "general.file_type": 15,
            "general.parameter_count": 0,
            **({f"{arch}.context_length": ctx_len, "llama.context_length": ctx_len} if ctx_len else {}),
        },
    }
    log.info("show  model=%s  type=%s  arch=%s  ctx=%s  caps=%s", model, lms_type, arch, ctx_len or "unknown", capabilities)
    return JSONResponse(payload)


@app.post("/api/chat", response_model=None)
async def chat(request: Request) -> StreamingResponse | JSONResponse:
    """
    Translate an Ollama /api/chat payload to OpenAI /chat/completions,
    forward it to LM Studio, then map the response back to Ollama format.
    Supports both streaming and non-streaming modes.
    """
    body: dict = await request.json()

    model: str = body.get("model", "")
    messages: list = body.get("messages", [])
    stream: bool = body.get("stream", False)
    options: dict = body.get("options", {})

    openai_payload: dict = {"model": model, "messages": messages, "stream": stream}
    for ollama_key, oai_key in OPTION_MAP.items():
        if ollama_key in options:
            openai_payload[oai_key] = options[ollama_key]

    log.info("chat  model=%s  stream=%s  messages=%d", model, stream, len(messages))

    if stream:
        return StreamingResponse(
            _stream_ollama_chunks(openai_payload),
            media_type="application/x-ndjson",
        )

    client = _get_client()
    try:
        resp = await client.post("v1/chat/completions", json=openai_payload)
        resp.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(502, "LM Studio server is not reachable. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "LM Studio did not respond within the timeout period.")
    except httpx.HTTPStatusError as exc:
        log.error("LM Studio %d: %s", exc.response.status_code, exc.response.text)
        raise HTTPException(exc.response.status_code, exc.response.text)

    data = resp.json()
    choice: dict = data.get("choices", [{}])[0]
    msg: dict = choice.get("message", {})
    usage: dict = data.get("usage", {})

    return JSONResponse({
        "model": model,
        "created_at": now_iso(),
        "message": {
            "role": msg.get("role", "assistant"),
            "content": msg.get("content", ""),
        },
        "done": True,
        "done_reason": choice.get("finish_reason", "stop"),
        "total_duration": 0,
        "load_duration": 0,
        "prompt_eval_count": usage.get("prompt_tokens", 0),
        "eval_count": usage.get("completion_tokens", 0),
    })


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def v1_passthrough(path: str, request: Request):
    """
    Transparent passthrough for any /v1/* request (embeddings, completions, etc.).
    Defined last so it does not shadow the more specific routes above.
    """
    client = _get_client()
    url = f"v1/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    # Strip hop-by-hop headers and the client's Authorization header.
    # The httpx client injects the LMS_API_KEY bearer token automatically
    # via its default headers, so we must not let the client's auth overwrite it.
    skip = {"host", "content-length", "transfer-encoding", "connection", "authorization"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}

    log.info("passthrough  %s /v1/%s", request.method, path)

    try:
        resp = await client.request(
            method=request.method,
            url=url,
            content=body,
            headers=headers,
        )
    except httpx.ConnectError:
        raise HTTPException(502, "LM Studio server is not reachable. Is it running?")
    except httpx.TimeoutException:
        raise HTTPException(504, "LM Studio did not respond in time.")

    return StreamingResponse(
        content=resp.aiter_bytes(),
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
    )
