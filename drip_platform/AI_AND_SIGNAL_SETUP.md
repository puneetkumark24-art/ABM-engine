# Turning on the AI, and what the signal pipeline actually does

Merged as `4164d21`. No schema change — nothing to migrate.

---

## 1. The AI model — answering your question directly

**No, I could not download a model for you.** Two hard reasons, not preferences:

- My sandbox is a separate Linux VM from your PC. Anything installed there
  disappears and never touches your machine.
- Its network blocks the model hosts anyway (`ollama.com` and `huggingface.co`
  both refused; I checked rather than assumed).

What I did instead is build the plumbing and prove it works, so the download is
the *only* step left and it's two commands.

### What to run

```
1. Install Ollama:      https://ollama.com/download   (Windows installer)
2. Pull a model:        ollama pull qwen2.5:7b
3. In drip_platform\.env add:
       LOCAL_LLM=true
4. Restart with "Restart DRIP Platform.bat"
```

Then open **AI Center** in the app. There's now a banner at the top telling you
exactly what's answering:

- 🟢 **LOCAL MODEL LIVE** — working
- 🔴 **LOCAL MODEL NOT RUNNING** — Ollama isn't started, or the model isn't pulled
- 🟡 **DRY-RUN — no AI connected** — no model; drafts fall back to templates

Before this, the only clue was the word "Dry-run" inside an analytics tile, so a
broken model looked identical to a working one.

### Which model

`qwen2.5:7b` is the default — about 4.7GB, good at business English, and runs on
16GB RAM. Alternatives, set with `LOCAL_LLM_MODEL` in `.env`:

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:3b` | ~2GB | If RAM is tight. Noticeably weaker copy. |
| `qwen2.5:7b` | ~4.7GB | **Default.** Best balance. |
| `llama3.1:8b` | ~4.7GB | Comparable; slightly better at long context. |
| `qwen2.5:14b` | ~9GB | Better, needs 32GB RAM. |

Costs nothing per call, works offline, and — the reason it matters for this
dataset — **no Saudi bank contact data leaves your machine.**

### If you'd rather use a cloud model

Already supported. Put `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
or `QWEN_API_KEY` in `.env` and leave `LOCAL_LLM` unset. Better quality than a
7B local model, but it costs per call and your contact data goes to that
provider. Local is checked first *only* when you explicitly set `LOCAL_LLM=true`,
so installing Ollama can never silently hijack a configured cloud provider.

### How I verified it without a model

`tests/test_local_llm.py` stands up a real HTTP server on a real port speaking
Ollama's exact protocol (`GET /v1/models`, `POST /v1/chat/completions`) and
drives real calls through the same entrypoint the engines use. Swap the port for
11434 and that *is* Ollama. 29 checks, including the failure you'll actually hit
— flag on, nothing listening — which must produce a logged error and never
invented text presented as a real answer.

---

## 2. The signal pipeline — and the break I found

### What it does, stage by stage

1. **Capture** — reads an RSS feed or official page. On my test feed: 3 items in,
   1 accepted as a real banking signal, 1 classed as market context, 1 rejected
   as noise (a football result).
2. **Attribution** — ties the item to a specific bank by name, alias and domain,
   and records a confidence (0.765 on my test item). An unrelated item gets no
   bank, rather than being force-fitted to one.
3. **Classification** — assigns type (`tender`), urgency (`CRITICAL`), and a
   decay category so the signal expires instead of looking fresh forever.
4. **Scoring** — relevance, source trust, and a **coverage cap** so one chatty
   source can't dominate an account's picture.
5. **Quality gate** — completeness, materiality, contradiction checks. Sets
   `scoring_eligible` and holds `action_eligible=0`: shadow mode is enforced in
   the engine itself, not just the UI.
6. **Deduplication** — re-ingesting the identical feed adds nothing.
7. **Export to CRM** — eligible, quality-passed, uncontested signals become real
   `Signal` rows against the right organization, tracked in a ledger so
   re-running never duplicates.
8. **Account rescore** — the new signal moves the account's signal score, which
   moves its tier, which is what the ABM screens rank on.

I drove all of that with real RSS bytes: **40/40 checks**.

### The break

**Signals for any bank registered at run time were captured, attributed,
classified, scored and quality-gated correctly — then silently dropped at the
last step.**

`build_account_map()` only ever looked at the static 11-bank catalog. Any bank
added through `Pipeline.add_account()` — which the API and the collectors both
use — was invisible to it, so its signals could never resolve to an
organization. Worse, the skip message read *"no reconciled organizations.id —
fix the name mismatch first"*, which sends you hunting through names when the
account was never in the lookup at all.

Every stage in isolation was correct. That is precisely why no existing test
caught it — and why I drove the whole chain instead of testing stages.

**Fixed:** the map now also reads the signal database's own accounts table,
`preview()` uses the same map as the export (so preview can't promise a row the
export then skips), and the skip reason tells you what to actually do.

`tests/test_signal_pipeline_e2e.py` now guards the entire chain, and asserts
*directly* that the catalog-only map does **not** see a runtime account — so the
regression can't come back quietly.

### One more, found on the way

A prompt with an unsubstituted `{{variable}}` was being sent to the model
verbatim. The QC gate checks the *output* for placeholders, so a mangled *input*
produced confident, plausible copy written around a literal `{{signal}}` with no
error anywhere. `call_llm` now refuses, names the missing variables, and logs it.

---

## 3. Honest status

**Working and tested:** capture, attribution, classification, decay, scoring,
coverage caps, quality gating, dedupe, CRM export, idempotency, account rescore,
the local-model adapter, and the AI status banner.

**Still open** — unchanged by this work, and none of it is something I can close
from here:

- **Signal coverage is 35.61% against a 90% target.** The pipeline is correct;
  it just isn't watching enough sources yet. That's a data-gathering job:
  more feeds and official pages registered as sources.
- **No human calibration sample.** Nobody has yet reviewed a batch of signals and
  confirmed the engine's judgements match a human's. Until then, "the quality
  gate works" means the code runs, not that its decisions are right.
- **LinkedIn has no official access path.**
- **Real outreach stays disabled.** Nothing here changes that.

The correct label is still **hardened local candidate, shadow/dry-run only**.

**On "flawless":** I can tell you 40/40 pipeline checks and 29/29 local-model
checks pass, and that I found two real defects doing it. I can't tell you the
system is flawless — the last three rounds each found something the round before
missed, and I'd expect the next round to find more. What I can say is that the
paths you asked about are now driven end to end by tests rather than assumed to
work.

---

## Rollback

```
git revert -m 1 4164d21
```
