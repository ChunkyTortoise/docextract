"""Guard README images and relative links against missing or broken assets.

The README first fold renders an image from ``docs/screenshots/``. If a branch
deletes or replaces that file (for example by resolving a modify/delete merge
conflict in favor of deletion), GitHub shows a broken image and nothing else
fails. These tests parse README.md, collect every relative image and link
target, and check that each one exists and, for images, is a small, valid file
with alt text.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_KINDS = frozenset({"img", "source", "md_image"})
ALT_REQUIRED_KINDS = frozenset({"img", "md_image"})
IGNORED_PREFIXES = ("http://", "https://", "mailto:", "#")

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG = re.compile(r"<(img|source)\b([^>]*)>", re.IGNORECASE)
_HTML_ATTR = re.compile(
    r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))"""
)
_MD_TARGET = r"""\(\s*<?([^\s)>]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)"""
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]" + _MD_TARGET)
# Link text may itself contain an inline image (badge pattern: [![alt](img)](url)).
_MD_LINK = re.compile(r"(?<!!)\[((?:[^\[\]]|!?\[[^\]]*\]\([^)]*\))*)\]" + _MD_TARGET)


@dataclass(frozen=True)
class Ref:
    kind: str  # one of: img, source, md_image, link
    target: str
    alt: str | None = None


def strip_fenced_code(markdown_text: str) -> str:
    """Blank out fenced code blocks (``` or ~~~), keeping line count stable."""
    out: list[str] = []
    fence: str | None = None
    for line in markdown_text.splitlines():
        if fence is None:
            match = _FENCE_OPEN.match(line)
            if match:
                fence = match.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence[0]}
                and len(stripped) >= len(fence)
                and len(line) - len(line.lstrip(" ")) <= 3
            ):
                fence = None
            out.append("")
    return "\n".join(out)


def _normalize(target: str) -> str | None:
    target = target.strip()
    if not target or target.lower().startswith(IGNORED_PREFIXES):
        return None
    target = re.split(r"[#?]", target, maxsplit=1)[0]
    while target.startswith("./"):
        target = target[2:]
    target = unquote(target)
    return target or None


def _attrs(raw: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _HTML_ATTR.finditer(raw):
        name = match.group(1).lower()
        value = next((g for g in match.groups()[1:] if g is not None), "")
        attrs.setdefault(name, value)
    return attrs


def collect_refs(markdown_text: str) -> list[Ref]:
    """Collect relative image and link targets that GitHub would render."""
    text = _HTML_COMMENT.sub("", strip_fenced_code(markdown_text))
    refs: list[Ref] = []

    for tag in _HTML_TAG.finditer(text):
        name = tag.group(1).lower()
        attrs = _attrs(tag.group(2))
        if name == "img":
            target = _normalize(attrs.get("src", ""))
            if target:
                refs.append(Ref("img", target, attrs.get("alt")))
        else:
            for candidate in attrs.get("srcset", "").split(","):
                parts = candidate.split()
                target = _normalize(parts[0]) if parts else None
                if target:
                    refs.append(Ref("source", target))

    for match in _MD_IMAGE.finditer(text):
        target = _normalize(match.group(2))
        if target:
            refs.append(Ref("md_image", target, match.group(1)))

    for match in _MD_LINK.finditer(text):
        target = _normalize(match.group(2))
        if target:
            refs.append(Ref("link", target, match.group(1)))

    return refs


def _image_type_problem(path: Path) -> str | None:
    suffix = path.suffix.lower()
    head = path.read_bytes()[:16]
    if suffix == ".png":
        ok = head.startswith(b"\x89PNG")
    elif suffix in {".jpg", ".jpeg"}:
        ok = head.startswith(b"\xff\xd8")
    elif suffix == ".gif":
        ok = head.startswith(b"GIF8")
    elif suffix == ".webp":
        ok = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    elif suffix == ".svg":
        try:
            root_tag = ET.parse(path).getroot().tag
        except ET.ParseError as exc:
            return f"invalid SVG XML ({exc})"
        ok = root_tag.endswith("svg")
    else:
        return f"unsupported image extension {suffix or '(none)'!r}"
    return None if ok else f"content does not match {suffix} signature"


def check_ref(ref: Ref, root: Path) -> list[str]:
    """Return a list of problems for one reference, or [] when it is fine."""
    problems: list[str] = []
    root = root.resolve()
    path = (root / ref.target.lstrip("/")).resolve()

    if not path.is_relative_to(root):
        return [f"{ref.target}: resolves outside the repository"]

    if ref.kind in ALT_REQUIRED_KINDS and not (ref.alt or "").strip():
        problems.append(f"{ref.target}: missing or empty alt text")

    if ref.kind in IMAGE_KINDS:
        if not path.is_file():
            problems.append(f"{ref.target}: image file does not exist")
            return problems
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            problems.append(f"{ref.target}: {size} bytes exceeds {MAX_IMAGE_BYTES} byte limit")
        type_problem = _image_type_problem(path)
        if type_problem:
            problems.append(f"{ref.target}: {type_problem}")
    elif not path.exists():
        problems.append(f"{ref.target}: link target does not exist")

    return problems


README_REFS = collect_refs(README.read_text(encoding="utf-8"))


@pytest.mark.parametrize("ref", README_REFS, ids=[ref.target for ref in README_REFS])
def test_readme_ref_resolves(ref: Ref) -> None:
    assert check_ref(ref, REPO_ROOT) == []


def test_readme_has_image_refs() -> None:
    assert any(ref.kind in IMAGE_KINDS for ref in README_REFS)


# Negative tests: each proves one failure mode is detected.

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _only(markdown_text: str) -> Ref:
    refs = collect_refs(markdown_text)
    assert len(refs) == 1, refs
    return refs[0]


def test_missing_image_file_detected(tmp_path: Path) -> None:
    ref = _only('<img src="./docs/missing.png" alt="hero">')
    assert ref == Ref("img", "docs/missing.png", "hero")
    assert any("does not exist" in p for p in check_ref(ref, tmp_path))


def test_img_with_empty_alt_detected(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG_BYTES)
    for html in ('<img alt="" src="a.png">', '<img src="a.png" width="10">'):
        problems = check_ref(_only(html), tmp_path)
        assert any("alt" in p for p in problems), html


def test_img_alt_before_src_is_parsed(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG_BYTES)
    ref = _only("<img alt='Hero shot' width=720 src='./a.png?raw=1'>")
    assert ref == Ref("img", "a.png", "Hero shot")
    assert check_ref(ref, tmp_path) == []


def test_md_image_with_empty_alt_detected(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG_BYTES)
    ref = _only("![](a.png)")
    assert ref.kind == "md_image"
    assert any("alt" in p for p in check_ref(ref, tmp_path))
    assert check_ref(_only("![diagram](a.png)"), tmp_path) == []


def test_oversize_image_detected(tmp_path: Path) -> None:
    (tmp_path / "big.png").write_bytes(PNG_BYTES + b"\x00" * MAX_IMAGE_BYTES)
    problems = check_ref(Ref("md_image", "big.png", "big"), tmp_path)
    assert any("exceeds" in p for p in problems)


def test_png_with_text_content_detected(tmp_path: Path) -> None:
    (tmp_path / "fake.png").write_text("version https://git-lfs.github.com/spec/v1\n")
    problems = check_ref(Ref("img", "fake.png", "fake"), tmp_path)
    assert any("signature" in p for p in problems)


def test_invalid_svg_detected(tmp_path: Path) -> None:
    (tmp_path / "broken.svg").write_text("<svg><g></svg>")
    (tmp_path / "html.svg").write_text("<html><body/></html>")
    (tmp_path / "ok.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert any("invalid SVG" in p for p in check_ref(Ref("md_image", "broken.svg", "x"), tmp_path))
    assert any("signature" in p for p in check_ref(Ref("md_image", "html.svg", "x"), tmp_path))
    assert check_ref(Ref("md_image", "ok.svg", "x"), tmp_path) == []


def test_source_srcset_urls_checked(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG_BYTES)
    refs = collect_refs('<source media="(min-width: 1px)" srcset="a.png 1x, ./b.png 2x">')
    assert refs == [Ref("source", "a.png"), Ref("source", "b.png")]
    assert check_ref(refs[0], tmp_path) == []
    assert any("does not exist" in p for p in check_ref(refs[1], tmp_path))


def test_missing_link_target_detected(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "DEMO.md").write_text("demo")
    assert check_ref(_only("[docs](docs/)"), tmp_path) == []
    assert check_ref(_only("[demo](./DEMO.md#run)"), tmp_path) == []
    problems = check_ref(_only("[gone](docs/GONE.md)"), tmp_path)
    assert any("link target does not exist" in p for p in problems)


def test_external_and_anchor_targets_ignored() -> None:
    text = (
        "[a](https://example.com) [b](http://x) [c](mailto:me@x.io) [d](#install)\n"
        "[![badge](https://img.shields.io/b.svg)](https://ci.example)\n"
        '<img src="https://example.com/a.png" alt="x">\n'
    )
    assert collect_refs(text) == []


def test_link_inside_fenced_code_block_ignored(tmp_path: Path) -> None:
    text = (
        "Intro [real](REAL.md)\n\n"
        "```bash\n"
        "echo '[ghost](missing.md)' ![x](missing.png)\n"
        '<img src="missing.png">\n'
        "```\n\n"
        "~~~~\n"
        "[ghost2](missing2.md)\n"
        "~~~~\n"
    )
    assert collect_refs(text) == [Ref("link", "REAL.md", "real")]


def test_link_outside_repo_root_detected(tmp_path: Path) -> None:
    problems = check_ref(Ref("link", "../outside.md", "x"), tmp_path)
    assert any("outside the repository" in p for p in problems)
