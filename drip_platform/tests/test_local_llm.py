"""Local-model provider — proven against a real HTTP server, not a mock object.

The point of this suite is that "the adapter compiles" and "the adapter can
talk to Ollama" are different claims. So it stands up an actual HTTP server on
a real port that speaks Ollama's OpenAI-compatible protocol (GET /v1/models,
POST /v1/chat/completions), points the provider at it, and drives real calls
through `call_llm` — the same entrypoint the engines use. Swap the port for
11434 and this is exactly what a running `ollama serve` does.

Also covers the failure everyone actually hits: the flag is on but no model
server is running. That must degrade to an honest dry-run, never to fabricated
text presented as a real answer.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from database import Base, engine, SessionLocal  # noqa: E402
import models_llm as ml  # noqa: E402
from abm_platform.services import llm_core  # noqa: E402

_results = []
RECEIVED = []          # what the fake server actually saw


def check(name, cond, detail=""):
    _results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + str(detail)) if detail else "")


class _Ollama(BaseHTTPRequestHandler):
    """A faithful stand-in for `ollama serve`'s OpenAI-compatible surface."""

    def log_message(self, *a):        # keep test output readable
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": "qwen2.5:7b", "object": "model"},
                {"id": "llama3.1:8b", "object": "model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        RECEIVED.append(payload)
        prompt = payload["messages"][-1]["content"]
        self._json(200, {
            "id": "chatcmpl-local", "object": "chat.completion",
            "model": payload.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": f"LOCAL REPLY to: {prompt[:60]}"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 17}})


def _start_server():
    srv = HTTPServer(("127.0.0.1", 0), _Ollama)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def _clear_env():
    for k in (llm_core.LOCAL_ENV_FLAG, llm_core.LOCAL_BASE_URL, llm_core.LOCAL_MODEL,
              "QWEN_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(k, None)


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    llm_core.set_test_provider(None)
    _clear_env()
    llm_core.ensure_prompt("local_probe", "Write one line about {{topic}}.")

    # ── 1. off by default ───────────────────────────────────────────────
    check("local provider is OFF unless explicitly enabled",
          llm_core.active_provider() is None)
    st = llm_core.local_llm_status()
    check("status says disabled, and says why", st["enabled"] is False and "dry-run" in st["detail"],
          st["detail"])

    # ── 2. flag on, but nothing listening ──────────────────────────────
    os.environ[llm_core.LOCAL_ENV_FLAG] = "true"
    os.environ[llm_core.LOCAL_BASE_URL] = "http://127.0.0.1:1/v1"   # nothing there
    st = llm_core.local_llm_status(timeout=2)
    check("enabled but unreachable is reported as NOT ready",
          st["enabled"] is True and st["reachable"] is False, st["detail"])
    check("the message tells you what to actually do",
          "ollama pull" in st["detail"], st["detail"])
    before = db.query(ml.LlmCall).count()
    out = llm_core.call_llm(db, "local_probe", {"topic": "KSA open banking"})
    check("an unreachable server produces an ERROR, never invented text",
          out["live"] is False and "[LLM ERROR]" in out["text"], out["text"][:70])
    check("the failed call is still logged for the cost/health view",
          db.query(ml.LlmCall).count() == before + 1)
    # Fetch BY ID, not order_by(id.desc()) -- the primary key is a UUID, so
    # ordering by it is not chronological and the "latest row" it returns is
    # arbitrary. (Cost this suite one confusing red before it was spotted.)
    check("the logged row records the failure honestly",
          db.get(ml.LlmCall, out["call_id"]).status == "error")

    # ── 3. a real server on a real port ────────────────────────────────
    srv, base = _start_server()
    try:
        os.environ[llm_core.LOCAL_BASE_URL] = base
        os.environ[llm_core.LOCAL_MODEL] = "qwen2.5:7b"

        st = llm_core.local_llm_status()
        check("a running server is detected", st["reachable"] is True, st["detail"])
        check("it lists the models the server has pulled",
              "qwen2.5:7b" in st["models_available"], st["models_available"])
        check("and confirms the configured model is one of them",
              st["detail"] == "local model ready", st["detail"])

        prov = llm_core.active_provider()
        check("local wins provider selection when enabled", prov and prov[0] == "local", prov)

        RECEIVED.clear()
        out = llm_core.call_llm(db, "local_probe", {"topic": "SAMA licensing"},
                                purpose="smoke", system="Be concise.")
        check("the call is LIVE, not a dry-run", out["live"] is True, out)
        check("the model's reply comes back", "LOCAL REPLY to:" in out["text"], out["text"][:60])
        check("the rendered prompt reached the model",
              RECEIVED and "SAMA licensing" in RECEIVED[0]["messages"][-1]["content"])
        check("the system prompt is passed through",
              RECEIVED and RECEIVED[0]["messages"][0]["content"] == "Be concise.")
        check("the configured model name is requested",
              RECEIVED and RECEIVED[0]["model"] == "qwen2.5:7b", RECEIVED[0].get("model"))
        check("token usage is recorded from the server's own numbers",
              out["cost_usd"] == 0.0, out["cost_usd"])
        row = db.get(ml.LlmCall, out["call_id"])
        check("the call row says provider=local and costs nothing",
              row.provider == "local" and row.tokens_in == 42
              and row.tokens_out == 17 and row.cost_usd == 0.0,
              f"{row.provider} {row.tokens_in}/{row.tokens_out} ${row.cost_usd}")

        # ── 4. a model that is not pulled is called out ────────────────
        os.environ[llm_core.LOCAL_MODEL] = "mistral-large:123b"
        st = llm_core.local_llm_status()
        check("a model that is not pulled is flagged, not silently used",
              st["reachable"] is True and "not pulled" in st["detail"], st["detail"])
        os.environ[llm_core.LOCAL_MODEL] = "qwen2.5:7b"

        # ── 5. an explicit cloud key does not hijack local ─────────────
        os.environ["OPENAI_API_KEY"] = "sk-not-a-real-key"
        prov = llm_core.active_provider()
        check("explicit local still wins over a stray cloud key",
              prov and prov[0] == "local", prov)
        os.environ.pop("OPENAI_API_KEY")

        # ── 6. and the engines actually use it ─────────────────────────
        # enable_ai() is what wires this layer into ai_gen; if that seam broke,
        # a working local model would still produce template drafts.
        from abm_platform.services import ai_gen  # noqa: E402
        captured = {}
        _orig_register = ai_gen.register_model
        ai_gen.register_model = lambda fn: captured.setdefault("fn", fn)
        try:
            wired = llm_core.enable_ai(SessionLocal)
        finally:
            ai_gen.register_model = _orig_register
        check("enable_ai reports the local provider as live", wired["live"] is True, wired)
        check("enable_ai registers a generator into ai_gen", "fn" in captured)
        # and that generator must really reach the local model
        RECEIVED.clear()
        text = captured["fn"]("email", {"role": "CDO", "segment": "bank",
                                        "signal": "open banking mandate"})
        check("the registered generator produces LOCAL model output",
              "LOCAL REPLY to:" in text, text[:60])
        check("the account signal reaches the model through that seam",
              RECEIVED and "open banking mandate" in RECEIVED[0]["messages"][-1]["content"])
    finally:
        srv.shutdown()
        _clear_env()
        llm_core.set_test_provider(None)

    # ── 7. a half-rendered prompt is refused, not sent ─────────────────
    llm_core.ensure_prompt("two_var_probe", "About {{alpha}} and {{beta}}.")
    out = llm_core.call_llm(db, "two_var_probe", {"alpha": "SAMA"})   # beta missing
    check("a prompt with a missing variable is NOT sent to the model",
          out["live"] is False and out["provider"] == "skipped", out["provider"])
    check("and it names the variable that was missing",
          out.get("missing_variables") == ["beta"], out.get("missing_variables"))
    check("the refusal is logged like any other failure",
          db.get(ml.LlmCall, out["call_id"]).status == "error")
    good = llm_core.call_llm(db, "two_var_probe", {"alpha": "SAMA", "beta": "open banking"})
    check("a fully rendered prompt is unaffected",
          "[PROMPT ERROR]" not in good["text"], good["text"][:50])

    # ── 8. back to honest dry-run once disabled ────────────────────────
    out = llm_core.call_llm(db, "local_probe", {"topic": "x"})
    check("with everything off it is a labelled DRY-RUN, not silence",
          out["live"] is False and "DRY-RUN" in out["text"], out["text"][:50])

    db.close()
    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{len(_results)} checks passed")
    return passed == len(_results)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)


def test_local_llm():
    assert run()
