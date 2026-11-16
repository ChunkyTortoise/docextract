"""Deterministic hallucination (faithfulness) scoring for extractions.

An extraction is a set of *claims*: every non-null leaf value the model returned
(``vendor_name = "Acme Corp"``, ``line_items[1].total = 200.0``, ...). A claim is
**grounded** when the value can be found in the source document text; otherwise it
is **unsupported** — the model asserted something the document does not say.

    faithfulness       = grounded_claims / scored_claims      (1.0 when nothing to score)
    hallucination_rate = 1 - faithfulness

This mirrors the definition DeepEval's ``FaithfulnessMetric`` uses (supported
claims over total claims, judged against the retrieval context), but the claim
check is a deterministic string/number/date match instead of an LLM judge, so it
runs in CI with no API key and gives the same answer on every run.

How a claim is matched, in order (the first that hits wins and is recorded as
the claim's ``match`` so a reviewer can see *why* it counted):

  exact     strings: case/whitespace-insensitive substring of the source
            numbers: equal (within 0.005) to a number printed in the source,
                     US ("1,080.00") or EU ("1.080,00") formatting
            dates:   the same calendar date appears in any common format
                     (ISO, 3/15/24, 15.03.2024, "Jan 15, 2024", "15 MAR 1985")
  ocr       the same, after folding OCR look-alikes (0/O, 1/l/I/|, 3/e, 4/a,
            5/s, rn/m) in both the value and the source. Scanned documents
            print "1OO.OO" for 100.00; reading that correctly is not invention.
  segments  a comma/semicolon-joined string whose every segment is grounded
            (a list the model flattened into one field)
  tokens    a short *name* field (<= 4 words) whose every word appears as a
            whole word in the source, e.g. "RODRIGUEZ MARIA ELENA" from separate
            Surname / Given Names lines

Fields that are a *normalization* rather than a copy of the text (ISO currency
codes, enum labels such as ``transaction_type`` or ``identity_document_type``,
gender codes) are listed in ``NORMALIZED_FIELDS`` and reported but not scored,
because the model is asked to map them onto a fixed vocabulary.

Known limitations (deliberately strict, flagged rather than forgiven):
  * a number the model *computed* (a total it added up) is unsupported unless
    the document prints it;
  * a paraphrase longer than four words ("Type 2 diabetes with hyperglycemia"
    for "... mellitus with hyperglycemia") is unsupported.
The per-claim report lets a reviewer separate those from real invention.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Leaf field names whose values are normalized labels, not verbatim spans.
NORMALIZED_FIELDS = frozenset(
    {
        "currency",
        "transaction_type",
        "identity_document_type",
        "document_type",
        "doc_type",
        "gender",
        "sex",
    }
)

MAX_TOKEN_MATCH_WORDS = 4

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

_NUM_TOKEN_RE = re.compile(r"(?<![\w])[-+]?\d[\d.,]*")
_OCR_NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[0-9OoIl|][0-9OoIl|.,]*(?![A-Za-z])")
_ISO_VALUE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ][\d:.]+Z?)?$")
_DMY_VALUE_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_WORD_RE = re.compile(r"[a-z0-9]+(?:['.\-][a-z0-9]+)*")

_OCR_FOLD = str.maketrans({"0": "o", "1": "l", "|": "l", "i": "l", "3": "e", "4": "a", "5": "s"})


@dataclass
class Claim:
    path: str
    value: Any
    kind: str  # "string" | "number" | "date" | "bool" | "normalized"
    grounded: bool | None  # None = not scored (normalized label / bool)
    match: str | None = None  # "exact" | "ocr" | "segments" | "tokens" | None


@dataclass
class GroundingResult:
    claims: list[Claim] = field(default_factory=list)

    @property
    def scored(self) -> list[Claim]:
        return [c for c in self.claims if c.grounded is not None]

    @property
    def unsupported(self) -> list[Claim]:
        return [c for c in self.claims if c.grounded is False]

    @property
    def faithfulness(self) -> float:
        scored = self.scored
        if not scored:
            return 1.0
        return sum(1 for c in scored if c.grounded) / len(scored)

    @property
    def hallucination_rate(self) -> float:
        return 1.0 - self.faithfulness


# ---------------------------------------------------------------------------
# Source indexing
# ---------------------------------------------------------------------------


def _norm_text(s: str) -> str:
    s = s.lower().replace(" ", " ")
    s = re.sub(r"[‘’]", "'", s)
    s = re.sub(r"[“”]", '"', s)
    return re.sub(r"\s+", " ", s).strip()


def _ocr_fold(s: str) -> str:
    return _norm_text(s).replace("rn", "m").translate(_OCR_FOLD)


def _parse_number(tok: str) -> list[float]:
    """Return every reading of a printed number (US and EU separators)."""
    tok = tok.strip(".,")
    if not tok or not re.search(r"\d", tok):
        return []
    seps = [c for c in tok if c in ",."]
    if not seps:
        styles = [("", ".")]
    elif len(set(seps)) == 2:
        # Both separators present: the last one is the decimal mark.
        styles = [(",", ".")] if seps[-1] == "." else [(".", ",")]
    elif re.fullmatch(r"[-+]?\d{1,3}([.,]\d{3})+", tok):
        # "1,250" / "1.250": a thousands separator, or (single group) a decimal mark.
        styles = [(seps[0], "#")] + ([("#", seps[0])] if len(seps) == 1 else [])
    else:
        # One kind of separator, not grouping thousands: it is the decimal mark.
        styles = [("#", seps[0])]
    readings: set[float] = set()
    for thousands, decimal in styles:
        t = tok.replace(thousands, "") if thousands else tok
        t = t.replace(decimal, ".") if decimal != "." else t
        try:
            readings.add(float(t))
        except ValueError:
            continue
    return sorted(readings)


def _ocr_digits(tok: str) -> str:
    return (
        tok.replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("l", "1")
        .replace("|", "1")
    )


class SourceIndex:
    """Pre-computed views of one source document."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.norm = _norm_text(source)
        self.folded = _ocr_fold(source)
        self.words = set(_WORD_RE.findall(self.norm))
        self.numbers = {n for tok in _NUM_TOKEN_RE.findall(source) for n in _parse_number(tok)}
        self.ocr_numbers = {
            n
            for tok in _OCR_NUM_TOKEN_RE.findall(source)
            if re.search(r"\d", tok)
            for n in _parse_number(_ocr_digits(tok))
        }
        self.dates = _source_dates(source)
        ocr_src = re.sub(r"(?<=[\d/.\-])[Oo]|[Oo](?=[\d/.\-])", "0", source)
        self.ocr_dates = _source_dates(ocr_src) - self.dates


def _mk_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _source_dates(source: str) -> set[date]:
    found: set[date] = set()
    s = source.lower()
    for y, m, d in re.findall(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", s):
        if dt := _mk_date(int(y), int(m), int(d)):
            found.add(dt)
    for a, b, y in re.findall(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})\b", s):
        a_i, b_i, y_i = int(a), int(b), int(y)
        for m, d in ((a_i, b_i), (b_i, a_i)):  # month-first and day-first both accepted
            if dt := _mk_date(y_i, m, d):
                found.add(dt)
    for mon, d, y in re.findall(
        rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", s
    ):
        if dt := _mk_date(int(y), _MONTHS[mon], int(d)):
            found.add(dt)
    for d, mon, y in re.findall(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-]+({_MONTH_ALT})\.?,?[\s\-]+(\d{{4}})\b", s
    ):
        if dt := _mk_date(int(y), _MONTHS[mon], int(d)):
            found.add(dt)
    return found


def _value_as_date(value: str) -> list[date]:
    v = value.strip()
    if m := _ISO_VALUE_RE.match(v):
        dt = _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return [dt] if dt else []
    if m := _DMY_VALUE_RE.match(v):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return [dt for dt in (_mk_date(y, b, a), _mk_date(y, a, b)) if dt]
    return []


# ---------------------------------------------------------------------------
# Claim extraction + checking
# ---------------------------------------------------------------------------


def iter_claims(obj: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield (path, leaf_key, value) for every non-null, non-empty leaf."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaf_or_recurse(v, f"{path}.{k}" if path else k, k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaf_or_recurse(v, f"{path}[{i}]", path.rsplit(".", 1)[-1])


def _leaf_or_recurse(v: Any, p: str, key: str) -> Iterator[tuple[str, str, Any]]:
    if isinstance(v, (dict, list)):
        yield from iter_claims(v, p)
    elif v is None or (isinstance(v, str) and not v.strip()):
        return
    else:
        yield p, key, v


def _match_string(text: str, idx: SourceIndex, key: str = "") -> str | None:
    norm = _norm_text(text)
    if norm in idx.norm:
        return "exact"
    if _ocr_fold(text) in idx.folded:
        return "ocr"
    dates = _value_as_date(text)
    if dates:
        if any(d in idx.dates for d in dates):
            return "exact"
        if any(d in idx.ocr_dates for d in dates):
            return "ocr"
        return None
    parts = [p for p in re.split(r"\s*[,;]\s*", text) if p.strip()]
    if len(parts) > 1 and all(_match_string(p, idx) in ("exact", "ocr") for p in parts):
        return "segments"
    words = _WORD_RE.findall(norm)
    if (
        "name" in key
        and 1 < len(words) <= MAX_TOKEN_MATCH_WORDS
        and all(w in idx.words for w in words)
    ):
        return "tokens"
    return None


def check_claim(key: str, value: Any, idx: SourceIndex) -> tuple[str, bool | None, str | None]:
    """Return (kind, grounded, match) for one leaf value."""
    if key in NORMALIZED_FIELDS:
        return "normalized", None, None
    if isinstance(value, bool):
        return "bool", None, None
    if isinstance(value, (int, float)):
        v = float(value)
        if any(abs(n - v) <= 0.005 for n in idx.numbers):
            return "number", True, "exact"
        if any(abs(n - v) <= 0.005 for n in idx.ocr_numbers):
            return "number", True, "ocr"
        return "number", False, None
    text = str(value)
    kind = "date" if _value_as_date(text) else "string"
    match = _match_string(text, idx, key)
    return kind, match is not None, match


def score_grounding(extraction: dict | None, source: str) -> GroundingResult:
    idx = SourceIndex(source or "")
    result = GroundingResult()
    for path, key, value in iter_claims(extraction or {}):
        kind, grounded, match = check_claim(key, value, idx)
        result.claims.append(
            Claim(path=path, value=value, kind=kind, grounded=grounded, match=match)
        )
    return result


__all__ = [
    "MAX_TOKEN_MATCH_WORDS",
    "NORMALIZED_FIELDS",
    "Claim",
    "GroundingResult",
    "SourceIndex",
    "check_claim",
    "iter_claims",
    "score_grounding",
]
