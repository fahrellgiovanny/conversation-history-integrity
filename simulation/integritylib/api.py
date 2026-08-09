"""integritylib.api - model call wrappers with retry and token accounting.

Gemini via the google-genai SDK (as mitigation_gemini.py); GLM via the
OpenAI-compatible ZhipuAI endpoint (as run_glm.py). Temperature 0, max
output 4096 tokens, one retry with 5 s backoff (per exclusion policy,
pre_registration.md section 4).
"""

import os
import socket

# Socket-level default timeout: a server that accepts a connection and then
# stays silent (observed with GLM-4.5-Air at its concurrency cap during peak
# hours) must raise socket.timeout instead of hanging forever. This is the
# only timeout that reliably fires when an SSL read (LibreSSL 2.8.3) holds
# the GIL and starves the SDK's own timeout timers (observed 2026-08-07:
# every thread deadlocked on PyThread_acquire_lock_timed).
socket.setdefaulttimeout(120)

from .config import MODEL_GEMINI, MODEL_GLM, MODEL_GPT, MAX_OUTPUT_TOKENS, TEMPERATURE

# Whole-request timeout for every model client (seconds for OpenAI-style
# SDKs, milliseconds for google-genai). Prevents a hung connection from
# stalling a worker forever (observed 2026-08-07).
REQUEST_TIMEOUT_MS = 180_000
REQUEST_TIMEOUT_S = 180

try:
    from google import genai
except ImportError:  # pragma: no cover - dry mode does not need SDKs
    genai = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


class DryModel:
    """Deterministic offline model for --dry verification runs."""

    def __init__(self):
        self.calls = 0

    def generate(self, prompt: str) -> dict:
        self.calls += 1
        return {
            "rawOutput": f"DRY_RESPONSE_{self.calls % 7}",
            "finishReason": "stop",
            "usageMetadata": {"promptTokens": 100, "completionTokens": 20,
                              "totalTokens": 120},
        }


class GeminiModel:
    def __init__(self, model: str = MODEL_GEMINI):
        if genai is None:
            raise RuntimeError("google-genai SDK not installed")
        self.model = model
        # Whole-request timeout (ms): a hung connection must not stall a
        # worker forever (observed 2026-08-07). SDK AUTO-RETRIES ARE OFF
        # (retry_options.attempts=0): the SDK's silent retries re-sent
        # ambiguous requests and double-billed (~$29 waste, 2026-08-07).
        # Every retry is controlled by call_with_retry instead.
        self.client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options={"timeout": REQUEST_TIMEOUT_MS,
                          "retry_options": {"attempts": 0}},
        )

    def generate(self, prompt: str) -> dict:
        r = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={"max_output_tokens": MAX_OUTPUT_TOKENS,
                    "temperature": TEMPERATURE},
        )
        fr = "unknown"
        try:
            fr = str(r.candidates[0].finish_reason.name) if r.candidates else "unknown"
        except Exception:
            pass
        usage = {}
        try:
            u = r.usage_metadata
            usage = {"promptTokens": u.prompt_token_count,
                     "completionTokens": u.candidates_token_count,
                     "totalTokens": u.total_token_count}
        except Exception:
            pass
        return {"rawOutput": r.text or "", "finishReason": fr, "usageMetadata": usage}


class GlmModel:
    def __init__(self, model: str = MODEL_GLM):
        if OpenAI is None:
            raise RuntimeError("openai SDK not installed")
        self.model = model
        self.client = OpenAI(api_key=os.environ["ZHIPUAI_API_KEY"],
                             base_url="https://open.bigmodel.cn/api/paas/v4",
                             max_retries=0)

    def generate(self, prompt: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=TEMPERATURE,
            timeout=REQUEST_TIMEOUT_S,
        )
        choice = resp.choices[0]
        return {
            "rawOutput": choice.message.content or "",
            "finishReason": str(choice.finish_reason) if choice.finish_reason else "unknown",
            "usageMetadata": {"promptTokens": resp.usage.prompt_tokens if resp.usage else 0,
                              "completionTokens": resp.usage.completion_tokens if resp.usage else 0,
                              "totalTokens": resp.usage.total_tokens if resp.usage else 0},
        }


class GptModel:
    """GPT-5.4 Mini via the OpenAI SDK (pattern of run_gpt.py). Used for the
    three-model determinism audit (EXP-1a/1b) and cross-model cells."""

    def __init__(self, model: str = MODEL_GPT):
        if OpenAI is None:
            raise RuntimeError("openai SDK not installed")
        self.model = model
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                             max_retries=0)

    def generate(self, prompt: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            temperature=TEMPERATURE,
            timeout=REQUEST_TIMEOUT_S,
        )
        choice = resp.choices[0]
        return {
            "rawOutput": choice.message.content or "",
            "finishReason": str(choice.finish_reason) if choice.finish_reason else "unknown",
            "usageMetadata": {"promptTokens": resp.usage.prompt_tokens if resp.usage else 0,
                              "completionTokens": resp.usage.completion_tokens if resp.usage else 0,
                              "totalTokens": resp.usage.total_tokens if resp.usage else 0},
        }


def make_model(model: str, dry: bool):
    if dry:
        return DryModel()
    if model == MODEL_GEMINI:
        return GeminiModel()
    if model == MODEL_GLM:
        return GlmModel()
    if model == MODEL_GPT:
        return GptModel()
    raise ValueError(f"unknown model {model}")


import threading
_thread_local = threading.local()


def get_model(model: str, dry: bool):
    """Thread-local client: one client per (worker thread, model, dry).

    A single OpenAI SDK 2.8 client shared across concurrent threads wedges
    in internal lock contention (observed 2026-08-07: 4 threads spinning in
    Python, zero progress, zero errors over 25 min; 4 separate clients
    worked fine). Each worker thread gets its own client, so no client is
    ever used by two threads at once.
    """
    key = (model, dry)
    cache = getattr(_thread_local, "models", None)
    if cache is None:
        cache = _thread_local.models = {}
    if key not in cache:
        cache[key] = make_model(model, dry)
    return cache[key]


def _fresh_model(model: str, dry: bool):
    """New client instance (breaks a stuck connection pool) for this thread."""
    return make_model(model, dry)


def _call_with_hard_timeout(model, prompt: str, timeout_s: int = REQUEST_TIMEOUT_S) -> dict:
    """Run the SDK call in a worker thread with a hard join timeout.

    SDK-level timeouts have proven unreliable for stuck connections
    (observed 2026-08-07: GLM requests hung >10 min with the OpenAI-style
    timeout parameter set). A join timeout always fires; the daemon thread
    is abandoned (small leak, acceptable for rare hangs).
    """
    box = {}

    def run():
        try:
            box["res"] = model.generate(prompt)
        except BaseException as e:  # noqa: BLE001 - must not lose the error
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(f"call exceeded {timeout_s}s (stuck connection)")
    if "err" in box:
        raise box["err"]
    return box["res"]


def call_with_retry(model, prompt: str) -> dict:
    """One call + one retry with 5 s backoff; failure returns an error row.

    GLM calls are serialized through GLM_MAX_CONCURRENCY (Zhipu's limit of 5
    concurrent requests); the semaphore covers the retry window too, so a
    retry never adds concurrency. On timeout the retry uses a FRESH client
    so a stuck connection pool cannot stall the retry as well.
    """
    import time as _time
    if isinstance(model, GlmModel):
        _GLM_SEM.acquire()
        try:
            return _call_once_hard(model, prompt)
        finally:
            _GLM_SEM.release()
    return _call_once_hard(model, prompt)


def _call_once_hard(model, prompt: str) -> dict:
    """One call + ONE retry ONLY on clean rejections (not billed).

    Cost policy (2026-08-07, user-confirmed):
    - TIMEOUT (ambiguous: the server may have processed AND billed the
      request): NO in-session retry - return an error row immediately;
      the session is purged and re-run once at batch end. Retrying here
      risks paying twice for the same request.
    - Clean rejections (429/503/5xx/connection errors - rejected before
      processing, NOT billed): one retry after 5 s with a fresh client.
    - 400s (content filter etc.): deterministic - never retried (same
      prompt fails identically; the runner excludes the session after two
      identical failures).
    """
    import time as _time
    t0 = _time.perf_counter()
    try:
        res = _call_with_hard_timeout(model, prompt)
        res["latency_ms"] = (_time.perf_counter() - t0) * 1000.0
        return res
    except TimeoutError as e:
        print(f"  TIMEOUT (may have billed): {e} - NO in-session retry; "
              f"session re-runs once at batch end")
        return {"rawOutput": "", "finishReason": "error",
                "usageMetadata": {"promptTokens": 0, "completionTokens": 0,
                                  "totalTokens": 0}, "latency_ms": 0.0}
    except Exception as e:
        if "Timeout" in type(e).__name__:
            print(f"  TIMEOUT (may have billed): {type(e).__name__} - NO retry")
            return {"rawOutput": "", "finishReason": "error",
                    "usageMetadata": {"promptTokens": 0, "completionTokens": 0,
                                      "totalTokens": 0}, "latency_ms": 0.0}
        print(f"  API ERROR (clean rejection, not billed): {e}; "
              f"one retry in 5s with a fresh client")
        _time.sleep(5)
        name = getattr(model, "model", None)
        if name is None:
            return {"rawOutput": "", "finishReason": "error",
                    "usageMetadata": {"promptTokens": 0, "completionTokens": 0,
                                      "totalTokens": 0}, "latency_ms": 0.0}
        try:
            fresh = _fresh_model(name, False)
            res = _call_with_hard_timeout(fresh, prompt)
            res["latency_ms"] = (_time.perf_counter() - t0) * 1000.0
            return res
        except TimeoutError:
            print("  TIMEOUT on retry (may have billed) - no further retry")
            return {"rawOutput": "", "finishReason": "error",
                    "usageMetadata": {"promptTokens": 0, "completionTokens": 0,
                                      "totalTokens": 0}, "latency_ms": 0.0}
        except Exception as e2:
            print(f"  API ERROR (retry failed): {e2}")
            return {"rawOutput": "", "finishReason": "error",
                    "usageMetadata": {"promptTokens": 0, "completionTokens": 0,
                                      "totalTokens": 0},
                    "latency_ms": 0.0}


import threading
from .config import GLM_MAX_CONCURRENCY as _GLM_MAX_CONCURRENCY
_GLM_SEM = threading.Semaphore(_GLM_MAX_CONCURRENCY)


def needs_key(model: str) -> None:
    env = ("GEMINI_API_KEY" if model == MODEL_GEMINI
           else ("ZHIPUAI_API_KEY" if model == MODEL_GLM else "OPENAI_API_KEY"))
    if env not in os.environ:
        raise RuntimeError(f"{env} not set (export it before running)")
