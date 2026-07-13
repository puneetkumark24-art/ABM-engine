"""
document_reader.py — deterministic, no-AI/no-API-key reading of unstructured
uploads (PDFs, images) so a bank's page and connection map update immediately
on upload instead of sitting in a "Pending — share with Claude" queue.

Two things happen here, both rule-based:
  1. Text extraction: pdfplumber for PDFs, pytesseract OCR for images (both
     run entirely on your machine — nothing leaves it, no API calls).
  2. Rule-based summarization + organization-name detection: takes the first
     readable paragraph as a "summary" and scans the rest of the text for
     Title-Case phrases that look like company/organization names, tagging
     each with a guessed relationship type (vendor/subsidiary/regulator/
     partner/competitor) based on nearby keywords.

This is intentionally NOT the same quality as an LLM reading the document —
it will miss things a human (or Claude, in a chat) would catch, and it can
flag false positives (any capitalized phrase can look like an org name).
That's why every detected name shows up as a one-click "Add to connection
map" suggestion rather than being silently written into OrgRelationship —
a human still confirms before it becomes a real connection.
"""
from __future__ import annotations
import io
import re
from collections import OrderedDict
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}
DOCUMENT_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS


def is_document_file(filename: str) -> str | None:
    """Returns 'pdf', 'image', or None (not an auto-readable type)."""
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return None


def extract_pdf_text(file_bytes: bytes) -> str:
    """Full text of every page, pdfplumber. Empty string for scanned/image-only
    PDFs (pdfplumber only reads embedded text, no OCR fallback for PDFs yet —
    if that's common for your dossiers, say the word and OCR can be added here too)."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return "\n".join(pages).strip()


_tesseract_path_checked = False


def _locate_tesseract_binary(pytesseract) -> None:
    """pytesseract normally just shells out to 'tesseract' on PATH. On Windows
    that's fragile: a `setx PATH` change from the installer doesn't reach
    processes that were already running, and a dashboard relaunched by
    double-clicking a .bat from File Explorer can inherit a stale environment
    from Explorer itself even after a fresh install — so 'tesseract --version'
    can work fine in a brand-new Command Prompt while the dashboard still
    can't find it. Rather than depend on PATH timing, check the handful of
    real install locations directly and point pytesseract straight at the
    binary if PATH lookup comes up empty. Runs once per process."""
    global _tesseract_path_checked
    if _tesseract_path_checked:
        return
    _tesseract_path_checked = True
    import shutil
    if shutil.which(pytesseract.pytesseract.tesseract_cmd or "tesseract"):
        return  # already resolvable via PATH — nothing to do
    import os
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return


def extract_image_text(file_bytes: bytes) -> str | None:
    """OCR via pytesseract. Returns None (not empty string) if the OCR engine
    itself isn't available on this machine, so the caller can tell 'no text
    found' apart from 'couldn't even try' and message the user accordingly."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    _locate_tesseract_binary(pytesseract)
    try:
        img = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(img).strip()
    except Exception:
        # Covers the case where pytesseract still can't find the Tesseract
        # binary even after the direct-path check above (TesseractNotFoundError
        # lives inside pytesseract and isn't worth importing just for this).
        return None


# ── Rule-based summary + organization-name detection ──────────────────────

_STOPWORDS = {
    "the", "and", "of", "for", "in", "on", "at", "to", "a", "an", "with", "by",
    "or", "as", "is", "are", "was", "were", "this", "that", "these", "those",
}
_TITLECASE_WORD = re.compile(r"^[A-Z][a-zA-Z&\.\-]*$")
_CONNECTOR_WORDS = {"of", "and", "the", "for", "&"}

# Common false positives that are Title-Case but not organizations — document
# boilerplate, headers, month names, and generic banking terms that show up
# in almost every dossier regardless of which bank it's about.
_ENTITY_STOPLIST = {
    "table of contents", "executive summary", "confidential", "appendix",
    "page", "figure", "chapter", "section", "overview", "introduction",
    "conclusion", "background", "january", "february", "march", "april",
    "may", "june", "july", "august", "september", "october", "november",
    "december", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "annual report", "board of directors", "kingdom of",
    "saudi arabia", "middle east", "united states", "united kingdom",
}

_RELATIONSHIP_KEYWORDS = [
    (("regulat", "central bank", "supervisory authority", "licensed by", "supervised by", "sama "),
     "regulator_of"),
    (("subsidiary", "wholly-owned", "wholly owned", "owned by", "parent company", "is part of"),
     "subsidiary"),
    (("core banking", "powered by", "provided by", "solution provider", "technology partner",
      "platform provider", "vendor"),
     "vendor"),
    (("partnership", "in partnership with", "strategic partner", "collaborat", "joint venture"),
     "partner"),
    (("competitor", "competing with", "rival to"),
     "competitor"),
]


def _extract_phrases(text: str) -> list[str]:
    """Finds runs of 2-4 Title-Case words (allowing lowercase connector words
    like 'of'/'and' in the middle, e.g. 'Bank of America'), which is a cheap
    but reasonable proxy for proper-noun organization names in English text."""
    words = re.findall(r"[A-Za-z&\.\-]+", text)
    phrases = []
    current: list[str] = []

    def flush():
        if len(current) >= 2:
            phrase = " ".join(current).strip()
            # Drop a trailing connector word ("Bank of" with nothing after)
            while current and current[-1].lower() in _CONNECTOR_WORDS:
                current.pop()
            if len(current) >= 2:
                phrases.append(" ".join(current))
        current.clear()

    for w in words:
        if _TITLECASE_WORD.match(w) and len(w) > 1:
            current.append(w)
        elif w.lower() in _CONNECTOR_WORDS and current:
            current.append(w.lower())
        else:
            flush()
    flush()
    return phrases


def _guess_relationship_type(text: str, phrase: str) -> tuple[str, str]:
    """Looks at the ~200-char window around each occurrence of `phrase` in
    `text` for relationship keywords, and picks whichever keyword sits
    CLOSEST to the phrase (by character distance) rather than the first type
    in priority order — a document with both "powered by X" right next to
    the name and "regulated by" two sentences later should tag X as a
    vendor, not a regulator, just because 'regulat' happened to also be
    inside the same 200-char window. Defaults to 'vendor' with no snippet if
    nothing nearby matches (this is a BD/ecosystem tool, so an unclassified
    mention is more useful bucketed as a vendor lead than dropped)."""
    idx = text.find(phrase)
    if idx == -1:
        return "vendor", ""
    window_start = max(0, idx - 100)
    window_end = min(len(text), idx + len(phrase) + 100)
    window = text[window_start:window_end]
    window_lower = window.lower()
    phrase_start_in_window = idx - window_start
    phrase_end_in_window = phrase_start_in_window + len(phrase)

    best_type, best_snippet, best_distance = None, "", None
    for keywords, rel_type in _RELATIONSHIP_KEYWORDS:
        for kw in keywords:
            search_from = 0
            while True:
                pos = window_lower.find(kw, search_from)
                if pos == -1:
                    break
                # Distance from the nearest edge of the phrase to this keyword occurrence.
                if pos >= phrase_end_in_window:
                    distance = pos - phrase_end_in_window
                elif pos + len(kw) <= phrase_start_in_window:
                    distance = phrase_start_in_window - (pos + len(kw))
                else:
                    distance = 0  # overlapping (shouldn't normally happen)
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_type = rel_type
                    best_snippet = " ".join(window.split())[:160]
                search_from = pos + 1

    if best_type is None:
        return "vendor", ""
    return best_type, best_snippet


def _build_summary(text: str, max_chars: int = 700) -> str:
    """First substantive paragraph/block of text, trimmed to a sentence
    boundary where possible. Not a real abstractive summary — just 'what
    appears first' — labeled as an excerpt on the page rather than oversold
    as an AI-generated summary."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Skip short all-caps/title lines at the very top (headers, letterhead)
    # so the excerpt starts from actual prose where possible.
    body_start = 0
    for i, l in enumerate(lines[:6]):
        if len(l) > 60 or (l[:1].islower() is False and " " in l and len(l.split()) > 8):
            body_start = i
            break
    block = " ".join(lines[body_start:body_start + 12])[:max_chars * 2]
    if len(block) <= max_chars:
        return block.strip()
    trimmed = block[:max_chars]
    last_period = trimmed.rfind(". ")
    if last_period > max_chars * 0.4:
        return trimmed[:last_period + 1].strip()
    return trimmed.rstrip() + "…"


def summarize_and_detect(text: str, exclude_name: str | None = None, max_entities: int = 15) -> dict:
    """Main entry point: given extracted text, returns {summary, entities}.
    entities is a list of {name, count, relationship_type, context}, ranked
    by (has a relationship-keyword nearby, mention count) and capped at
    max_entities. exclude_name (the bank's own name) is filtered out so a
    document doesn't suggest 'connect Riyad Bank to Riyad Bank'."""
    if not text or not text.strip():
        return {"summary": "", "entities": []}

    phrases = _extract_phrases(text)
    counts: "OrderedDict[str, int]" = OrderedDict()
    for p in phrases:
        key = p.strip()
        norm = key.lower()
        if norm in _ENTITY_STOPLIST or len(norm) < 4:
            continue
        if exclude_name and norm == exclude_name.strip().lower():
            continue
        counts[key] = counts.get(key, 0) + 1

    scored = []
    for name, count in counts.items():
        rel_type, context = _guess_relationship_type(text, name)
        has_keyword = bool(context)
        scored.append({
            "name": name, "count": count,
            "relationship_type": rel_type, "context": context,
            "_has_keyword": has_keyword,
        })

    scored.sort(key=lambda e: (e["_has_keyword"], e["count"]), reverse=True)
    entities = []
    seen_lower = set()
    for e in scored:
        norm = e["name"].lower()
        if norm in seen_lower:
            continue
        seen_lower.add(norm)
        entities.append({"name": e["name"], "count": e["count"],
                          "relationship_type": e["relationship_type"], "context": e["context"]})
        if len(entities) >= max_entities:
            break

    return {"summary": _build_summary(text), "entities": entities}


def process_uploaded_document(upload, bank_name: str | None) -> None:
    """Mutates `upload` (a models.DocumentUpload instance) in place with
    extracted_text / extracted_summary / detected_entities / status /
    processing_notes. Does NOT commit — caller owns the transaction. Raises
    on genuinely unexpected errors (e.g. corrupt file) so the route can catch
    it and mark the upload 'failed' with the real error rather than silently
    losing the file."""
    from datetime import datetime

    doc_type = is_document_file(upload.filename)
    if doc_type is None:
        return  # not our job — leave whatever status the caller already set

    if doc_type == "pdf":
        text = extract_pdf_text(upload.file_data)
        if not text:
            upload.status = "processed"
            upload.extracted_text = ""
            upload.processing_notes = ("Stored, but no extractable text was found — likely a scanned/"
                                        "image-only PDF. OCR isn't run automatically on PDFs yet; if your "
                                        "dossiers are usually scans, ask to have that added.")
            return
    else:  # image
        text = extract_image_text(upload.file_data)
        if text is None:
            upload.status = "processed"
            upload.extracted_text = ""
            upload.processing_notes = ("Stored, but OCR isn't available on this machine (Tesseract isn't "
                                        "installed/on PATH) — install Tesseract OCR to enable automatic "
                                        "text reading from images. The image itself is saved either way.")
            return
        if not text.strip():
            upload.status = "processed"
            upload.extracted_text = ""
            upload.processing_notes = "Stored — OCR ran but found no readable text in this image."
            return

    result = summarize_and_detect(text, exclude_name=bank_name)
    upload.extracted_text = text[:20000]
    upload.extracted_summary = result["summary"]
    upload.detected_entities = result["entities"]
    upload.status = "processed"
    upload.processed_at = datetime.utcnow()
    upload.processing_notes = (
        f"Auto-read on upload: {len(text):,} characters extracted, "
        f"{len(result['entities'])} organization mention(s) detected below — "
        f"review and add any real ones to the connection map."
    )
