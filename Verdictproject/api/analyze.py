"""Vercel Python serverless function: run the REAL Verdict judgment pipeline on an uploaded file.

Honesty (Constraint A): this project has no document reader. We extract only genuinely real,
lightweight facts from the bytes (SHA-256 -> deterministic seed, size, type, best-effort PDF
page count) and feed the seed into the SAME synthetic field-generation model the offline
experiment uses. Extraction is therefore SIMULATED. What is genuinely LIVE is the judgment
layer: the field loop, three-path discrimination, calibrated routing and the ACI threshold
update all run on the real code in src/abstention — not a replay of a recorded run, and not a
second implementation. The response is shaped exactly like one analysis in report.json, so the
existing processing screen and workspace render it unchanged.

Privacy (Constraint B): the uploaded bytes live only in memory for the single request. Nothing
is written to disk; the filename and contents are never logged. Validation rejects oversized or
unsupported files cleanly; a best-effort in-memory rate limit guards the public endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

# --- make the real pipeline importable (src/ sits beside api/ under the Vercel root) --------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # Verdictproject/
for _p in (os.path.join(_ROOT, "src"), _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- limits / policy ------------------------------------------------------------------------
MAX_BYTES = 8 * 1024 * 1024  # 8 MB hard cap (also the main abuse guard)
ALLOWED = {"pdf", "png", "jpg", "jpeg", "csv", "txt", "tsv"}
RATE_MAX = 20          # requests
RATE_WINDOW = 60.0     # seconds, per client IP — best-effort, per warm instance (see note below)
LIVE_N_CASES = 360     # enough to warm up the ACI threshold; kept small so the function is fast

SIM_NOTICE = (
    "SIMULATED EXTRACTION. This demo does not read your document's contents. It derives a "
    "deterministic seed from the file (SHA-256) and runs the real judgment pipeline "
    "(field loop, three-path routing, ACI threshold) on a synthetic case. Only the judgment "
    "layer is live; extraction is simulated."
)

# best-effort fixed-window rate limit. NOTE: serverless instances are ephemeral and not shared,
# so this resets on cold start and is per-instance — it is a courtesy guard, not a hard quota.
# The real hard guard is MAX_BYTES + the type allowlist. A durable limit would need external KV.
_HITS: dict[str, list[float]] = {}


class ValidationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _detect_type(data: bytes, filename: str) -> str:
    """Real type detection from magic bytes, falling back to the extension. No content parsing."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ALLOWED:
        return "jpg" if ext == "jpg" else ext
    if ext:
        # a named-but-disallowed extension (.exe, .zip, .docx…) is rejected outright — we do NOT
        # fall through to text-sniffing, so an ASCII payload named .exe cannot pass as txt
        return "unknown"
    # only extensionless files are sniffed as plain text
    try:
        data[:2048].decode("utf-8")
        return "csv" if (b"," in data[:4096] and b"\n" in data[:4096]) else "txt"
    except UnicodeDecodeError:
        return "unknown"


def _pdf_page_count(data: bytes) -> int | None:
    """Best-effort, lightweight page count for PDFs — counts /Type /Page objects. Approximate;
    never claims to read the page's contents."""
    if data[:5] != b"%PDF-":
        return None
    import re
    n = len(re.findall(rb"/Type\s*/Page[^s]", data))
    return n or None


def _validate(data: bytes, filename: str) -> str:
    if not data:
        raise ValidationError(400, "Empty file. Choose a document to submit.")
    if len(data) > MAX_BYTES:
        raise ValidationError(413, f"File is larger than the {MAX_BYTES // (1024 * 1024)} MB limit.")
    ftype = _detect_type(data, filename)
    if ftype not in ALLOWED:
        raise ValidationError(
            415, "Unsupported file type. Allowed: PDF, PNG, JPG, CSV, TXT, TSV.")
    return ftype


def _rate_limit(ip: str) -> None:
    now = time.time()
    hits = [t for t in _HITS.get(ip, ()) if now - t < RATE_WINDOW]
    if len(hits) >= RATE_MAX:
        raise ValidationError(429, "Too many requests. Wait a minute and try again.")
    hits.append(now)
    _HITS[ip] = hits


def _seed_from(data: bytes) -> tuple[int, str]:
    digest = hashlib.sha256(data).hexdigest()
    seed = int(digest[:16], 16)  # deterministic per file
    return seed, digest


def run_live_analysis(data: bytes, filename: str) -> dict:
    """Pure core (no HTTP): validate, extract real file facts, run the real pipeline on a
    file-seeded synthetic case, and return a report.json-shaped analysis plus file metadata.
    Raises ValidationError on bad input. Never touches disk; never logs contents."""
    ftype = _validate(data, filename)
    seed, digest = _seed_from(data)

    # import the REAL pipeline (stdlib-only at runtime; PyYAML just reads the existing config)
    import yaml
    from abstention.data.synthetic import SyntheticStream, stream_config_from_mapping
    from abstention.deferral.reviewer_model import ReviewerAccuracyModel
    from abstention.experiment.file_analysis import _BatchContext, _build_analysis
    from abstention.loops.field_loop import FieldInput, FieldLoop, FieldLoopConfig

    with open(os.path.join(_ROOT, "configs", "baseline.yaml")) as fh:
        cfg = yaml.safe_load(fh)
    cfg = dict(cfg)
    cfg["stream"] = dict(cfg["stream"])
    cfg["stream"]["n_cases"] = LIVE_N_CASES

    stream = SyntheticStream(stream_config_from_mapping(cfg, seed=seed))
    cases = stream.cases()
    rm = ReviewerAccuracyModel(accuracy_by_field={}, default_accuracy=0.70)
    loop = FieldLoop(
        FieldLoopConfig(r_star=cfg["alpha"], alpha=cfg["alpha"], gamma=max(cfg["gamma"], 0.02),
                        min_calibration=100, quantile_window=800,
                        budget_per_batch=cfg["reviewer_budget_per_batch"]),
        rm, random.Random(seed),
    )
    cpb = 300 // stream.config.fields_per_case
    batches = [cases[i:i + cpb] for i in range(0, len(cases), cpb)]
    ctxs: list[tuple[list, object]] = []
    for bi, cbatch in enumerate(batches):
        inputs = [
            FieldInput(field_type=lf.field_type, calibrated_confidence=lf.confidence,
                       true_error=lf.true_error, segment=case.segment)
            for case in cbatch for lf in case.labeled_fields
        ]
        if not inputs:
            continue
        res = loop.process_batch(f"batch-{bi:03d}", inputs)
        ctxs.append((cbatch, _BatchContext(batch_id=res.batch_id, tau=res.tau_t, alpha_t=res.alpha_t)))

    warm = [(cb, ctx) for cb, ctx in ctxs if ctx.tau > 0.0] or ctxs
    cbatch, ctx = warm[seed % len(warm)]
    case = cbatch[seed % len(cbatch)]
    analysis = _build_analysis(case, ctx, datetime.now(timezone.utc).isoformat())

    # relabel for display so the case reads as the user's upload, not an internal case id
    short = digest[:8]
    analysis["file_label"] = filename[:80]
    analysis["case_id"] = "LIVE-" + short.upper()
    analysis["live"] = True

    return {
        "ok": True,
        "simulated": True,
        "notice": SIM_NOTICE,
        "file": {
            "name": filename[:120],
            "size": len(data),
            "type": ftype,
            "sha256": digest,
            "pages": _pdf_page_count(data),
        },
        "analysis": analysis,
    }


class handler(BaseHTTPRequestHandler):
    # suppress default request logging entirely so no filename/path is ever written to logs
    def log_message(self, *args):  # noqa: D401
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # capability probe used by the UI to know the live endpoint exists
        self._send(200, {"ok": True, "endpoint": "analyze", "simulated": True,
                         "notice": SIM_NOTICE, "maxBytes": MAX_BYTES,
                         "allowed": sorted(ALLOWED)})

    def do_POST(self):
        try:
            ip = (self.headers.get("x-forwarded-for", "") or self.client_address[0] or "anon").split(",")[0].strip()
            _rate_limit(ip)
            length = int(self.headers.get("content-length") or 0)
            if length > MAX_BYTES:
                raise ValidationError(413, f"File is larger than the {MAX_BYTES // (1024 * 1024)} MB limit.")
            data = self.rfile.read(length) if length else b""
            from urllib.parse import unquote
            filename = unquote((self.headers.get("x-filename") or "upload").strip()) or "upload"
            result = run_live_analysis(data, filename)
            # explicit privacy hygiene: drop the bytes reference as soon as we're done
            del data
            self._send(200, result)
        except ValidationError as e:
            self._send(e.status, {"ok": False, "error": e.message})
        except Exception:
            # never leak internals or file data in an error; keep it generic
            self._send(500, {"ok": False, "error": "The analysis pipeline failed on this input."})
