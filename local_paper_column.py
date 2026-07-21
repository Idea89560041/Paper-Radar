#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build local reading notes from PDFs added to a OneDrive folder.

This script is intended to run on the user's Windows machine, because GitHub
Actions cannot access local OneDrive paths such as D:\\OneDrive...
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_LIBRARY_DIR = r"D:\OneDrive - The Chinese University of Hong Kong\Paper_Radar"


TOPIC_TERMS = {
    "Neuroimaging": ["neuroimaging", "neuroimage", "brain MRI", "brain imaging", "fMRI", "PET"],
    "BCI / EEG": [
        "brain-computer interface",
        "brain computer interface",
        "BCI",
        "EEG",
        "electroencephalography",
        "neural decoding",
        "motor imagery",
    ],
    "AD / Dementia": ["Alzheimer", "dementia", "MCI", "mild cognitive impairment", "amyloid", "tau"],
    "Foundation / VLM": ["foundation model", "vision-language", "large multimodal", "large language model", "SAM"],
    "Generative AI": ["diffusion", "generative", "GAN", "VAE", "synthesis", "imputation"],
    "Multi-organ": ["whole-body", "whole body", "total-body", "multi-organ", "PET/MRI"],
    "Learning Methods": ["self-supervised", "contrastive", "domain adaptation", "federated", "transformer"],
}

METHOD_TERMS = [
    "transformer",
    "foundation model",
    "diffusion",
    "GAN",
    "graph neural",
    "contrastive",
    "self-supervised",
    "domain adaptation",
    "federated",
    "reinforcement learning",
    "neural network",
    "deep learning",
    "machine learning",
]

MODALITY_TERMS = ["MRI", "fMRI", "PET", "EEG", "MEG", "CT", "brain signal", "neuroimaging"]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = text.replace("\x00", " ")
    return re.sub(r"\s+", " ", text).strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_pdf(path: Path, max_pages: int, max_chars: int) -> Dict[str, str]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("Missing pypdf. Install requirements.txt before scanning PDFs.") from exc

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    title = clean_text(getattr(meta, "title", "") or meta.get("/Title", ""))
    authors = clean_text(getattr(meta, "author", "") or meta.get("/Author", ""))

    parts: List[str] = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
        if sum(len(part) for part in parts) >= max_chars:
            break
    text = clean_text("\n".join(parts))[:max_chars]
    if not title or len(title) < 8 or title.lower() in {"untitled", "unknown"}:
        title = infer_title(text, path)
    return {"title": title, "authors": authors, "text": text}


def infer_title(text: str, path: Path) -> str:
    lines = [clean_text(line) for line in re.split(r"[\n\r]+|(?<=\.)\s{2,}", text[:2500])]
    skip_patterns = [
        r"^arxiv:",
        r"^doi:",
        r"^http",
        r"^www\.",
        r"^abstract$",
        r"^keywords?",
        r"^received",
        r"^accepted",
        r"^copyright",
    ]
    for line in lines:
        if len(line) < 12 or len(line) > 220:
            continue
        if any(re.search(pattern, line, re.I) for pattern in skip_patterns):
            continue
        if sum(ch.isalpha() for ch in line) < 8:
            continue
        return line.rstrip(".")
    return path.stem.replace("_", " ").replace("-", " ").strip()


def extract_abstract(text: str) -> str:
    match = re.search(r"\babstract\b(.{200,2500}?)(?:\bintroduction\b|\bkeywords?\b|1\s+introduction)", text, re.I)
    if match:
        return clean_text(match.group(1))[:1600]
    return clean_text(text[:1400])


def detect_topics(text: str) -> List[str]:
    text_l = text.lower()
    topics = []
    for label, terms in TOPIC_TERMS.items():
        if any(has_term(text_l, term) for term in terms):
            topics.append(label)
    return topics[:5] or ["Medical AI"]


def has_term(text_l: str, term: str) -> bool:
    term_l = term.lower()
    if re.fullmatch(r"[a-z0-9]{2,4}", term_l):
        return re.search(rf"\b{re.escape(term_l)}\b", text_l) is not None
    return term_l in text_l


def pick_terms(text: str, terms: Iterable[str], fallback: str) -> str:
    text_l = text.lower()
    found = [term for term in terms if has_term(text_l, term)]
    return ", ".join(found[:4]) if found else fallback


def first_informative_sentence(text: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+", clean_text(text)):
        sentence = clean_text(sentence.strip(" .,-:;"))
        if 80 <= len(sentence) <= 320:
            return sentence
    return clean_text(text[:260])


def split_points(text: str, limit: int = 3) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", clean_text(text))
    points = []
    for sentence in sentences:
        sentence = clean_text(sentence.strip(" .,-:;"))
        if 60 <= len(sentence) <= 260:
            points.append(sentence)
        if len(points) >= limit:
            break
    return points or [clean_text(text[:220]) or "需要阅读全文进一步确认核心贡献。"]


def heuristic_note(title: str, text: str, topics: List[str]) -> Dict[str, Any]:
    abstract = extract_abstract(text)
    method = pick_terms(text, METHOD_TERMS, "deep learning / machine learning")
    modality = pick_terms(text, MODALITY_TERMS, "brain or medical imaging data")
    topic_text = "、".join(topics)
    lead = first_informative_sentence(abstract or text)
    method_l = method.lower()
    ideas = [
        "检查其数据模态、任务定义和评价指标是否能迁移到你的 neuroimaging / medical AI 方向。",
        "关注模型是否解决跨中心、跨被试、缺失模态或小样本泛化问题。",
        "如果方法有可复用模块，可考虑和你的现有 MRI/PET/脑影像任务做组合实验。",
    ]
    if "diffusion" in method_l or "generative" in method_l or "gan" in method_l:
        ideas[0] = "优先关注它能否用于缺失模态补全、纵向影像预测、低剂量/低质量图像增强或跨模态合成。"
    if any(topic in topics for topic in ["AD / Dementia", "Multi-organ"]):
        ideas[1] = "可以重点看它是否能扩展到 AD/MCI 风险预测、多器官影像表征或跨疾病泛化验证。"
    return {
        "one_sentence": f"这篇论文围绕“{title}”，核心线索是：{lead}",
        "why_relevant": f"它与 {topic_text} 相关，且方法上涉及 {method}，数据/模态侧重 {modality}，适合作为医学影像 AI 选题发散或方法迁移的候选文献。",
        "data_modality": modality,
        "method": method,
        "key_points": split_points(abstract, limit=3),
        "limitations": "自动解读基于 PDF 前几页文本抽取生成，建议结合全文实验设置、数据来源和外部验证结果进一步判断可靠性。",
        "ideas": ideas,
    }


def openai_note(title: str, text: str, topics: List[str]) -> Dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = f"""请为医学影像AI研究者用中文解读下面这篇论文。只根据给定文本，不要编造。
返回严格 JSON，字段为：
one_sentence, why_relevant, data_modality, method, key_points(list of 3 strings),
limitations, ideas(list of 3 strings)。

Title: {title}
Detected topics: {", ".join(topics)}
Text:
{text[:12000]}
"""
        response = client.responses.create(model=model, input=prompt)
        raw = clean_text(getattr(response, "output_text", ""))
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.I).strip()
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        print(f"[warn] OpenAI interpretation failed for {title[:80]}: {exc}", file=sys.stderr)
    return None


def wrap_svg_text(text: str, width: int) -> List[str]:
    lines: List[str] = []
    for part in textwrap.wrap(clean_text(text), width=width):
        lines.append(part)
    return lines[:4] or [""]


def svg_text_block(lines: List[str], x: int, y: int, size: int, fill: str, weight: int = 500) -> str:
    out = []
    for i, line in enumerate(lines):
        out.append(
            f'<text x="{x}" y="{y + i * (size + 8)}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}">{html.escape(line)}</text>'
        )
    return "\n".join(out)


def build_visual_svg(reading: Dict[str, Any], out_path: Path) -> None:
    title_lines = wrap_svg_text(reading.get("title", "Reading note"), 54)
    topics = reading.get("topics", [])[:4]
    method = clean_text(reading.get("interpretation", {}).get("method", "method"))
    modality = clean_text(reading.get("interpretation", {}).get("data_modality", "data"))
    one_sentence = clean_text(reading.get("interpretation", {}).get("one_sentence", ""))

    topic_spans = []
    x = 64
    palette = ["#0b5cad", "#0f766e", "#8a4b0f", "#5b5f97"]
    for idx, topic in enumerate(topics or ["Medical AI"]):
        color = palette[idx % len(palette)]
        width = max(130, min(300, 18 * len(topic)))
        topic_spans.append(
            f'<rect x="{x}" y="292" width="{width}" height="38" rx="8" fill="{color}" opacity="0.12"/>'
            f'<text x="{x + 14}" y="317" font-size="18" font-weight="700" fill="{color}">{html.escape(topic)}</text>'
        )
        x += width + 14

    flow = [
        ("Question", reading.get("title", "")[:44]),
        ("Modality", modality[:44]),
        ("Method", method[:44]),
        ("Use", "idea screening / follow-up reading"),
    ]
    flow_blocks = []
    for idx, (label, value) in enumerate(flow):
        bx = 64 + idx * 274
        flow_blocks.append(
            f'<rect x="{bx}" y="388" width="238" height="112" rx="10" fill="#ffffff" stroke="#d8e0e7"/>'
            f'<text x="{bx + 18}" y="424" font-size="17" font-weight="760" fill="#172026">{html.escape(label)}</text>'
            f'{svg_text_block(wrap_svg_text(str(value), 22)[:2], bx + 18, 458, 14, "#64717d", 520)}'
        )
        if idx < len(flow) - 1:
            flow_blocks.append(
                f'<path d="M {bx + 246} 444 L {bx + 266} 444" stroke="#0f766e" stroke-width="3"/>'
                f'<path d="M {bx + 266} 444 L {bx + 258} 437 M {bx + 266} 444 L {bx + 258} 451" '
                f'stroke="#0f766e" stroke-width="3" fill="none"/>'
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="680" viewBox="0 0 1200 680">
  <rect width="1200" height="680" fill="#f5f7f9"/>
  <rect x="34" y="34" width="1132" height="612" rx="18" fill="#ffffff" stroke="#d8e0e7"/>
  <text x="64" y="88" font-family="Arial, sans-serif" font-size="20" font-weight="760" fill="#0f766e">Paper Radar Reading Note</text>
  <text x="64" y="126" font-family="Arial, sans-serif" font-size="14" fill="#64717d">{html.escape(reading.get("processed_at", "")[:10])} / {html.escape(reading.get("source_file", ""))}</text>
  <g font-family="Arial, sans-serif">
    {svg_text_block(title_lines, 64, 182, 32, "#172026", 780)}
    {''.join(topic_spans)}
    {''.join(flow_blocks)}
    <rect x="64" y="548" width="1072" height="58" rx="10" fill="#e8f1fb"/>
    {svg_text_block(wrap_svg_text(one_sentence, 115)[:2], 86, 582, 16, "#33414d", 560)}
  </g>
</svg>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")


def process_pdf(path: Path, args: argparse.Namespace) -> Dict[str, Any]:
    digest = file_sha256(path)
    extracted = extract_pdf(path, max_pages=args.max_pages, max_chars=args.max_chars)
    title = extracted["title"]
    text = extracted["text"]
    topics = detect_topics(" ".join([title, text]))
    note = None if args.no_openai else openai_note(title, text, topics)
    if not note:
        note = heuristic_note(title, text, topics)

    processed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    reading = {
        "id": digest[:16],
        "sha256": digest,
        "title": title,
        "authors": extracted.get("authors", ""),
        "source_file": path.name,
        "file_size": path.stat().st_size,
        "file_mtime": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
        "processed_at": processed_at,
        "topics": topics,
        "interpretation": note,
        "image_path": str(Path(args.assets_dir) / f"{digest[:16]}.svg").replace("\\", "/"),
        "text_excerpt": extract_abstract(text)[:900],
    }
    build_visual_svg(reading, Path(reading["image_path"]))
    return reading


def scan_pdfs(library_dir: Path, recursive: bool) -> List[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(library_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library-dir", default=os.getenv("PAPER_RADAR_LIBRARY_DIR", DEFAULT_LIBRARY_DIR))
    parser.add_argument("--readings-path", default="data/local_readings.json")
    parser.add_argument("--state-path", default="data/local_library_state.json")
    parser.add_argument("--assets-dir", default="data/reading_assets")
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--max-chars", type=int, default=18000)
    parser.add_argument("--max-new", type=int, default=20)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--no-openai", action="store_true")
    parser.add_argument("--refresh-existing", action="store_true", help="Rebuild notes for PDFs already in the local state.")
    args = parser.parse_args()

    library_dir = Path(args.library_dir)
    if not library_dir.exists():
        raise FileNotFoundError(f"Library folder does not exist: {library_dir}")

    readings_path = Path(args.readings_path)
    state_path = Path(args.state_path)
    readings = load_json(readings_path, [])
    if not isinstance(readings, list):
        readings = []
    state = load_json(state_path, {"files": {}, "updated_at": None})
    if not isinstance(state, dict):
        state = {"files": {}, "updated_at": None}
    files_state = state.setdefault("files", {})

    known_hashes = set(files_state)
    known_hashes.update(item.get("sha256", "") for item in readings if isinstance(item, dict))
    new_readings = []
    processed_hashes = set()
    for pdf_path in scan_pdfs(library_dir, recursive=args.recursive):
        digest = file_sha256(pdf_path)
        if digest in known_hashes and not args.refresh_existing:
            continue
        action = "Refreshing" if digest in known_hashes else "Processing"
        print(f"[info] {action} {pdf_path.name}")
        try:
            reading = process_pdf(pdf_path, args)
        except Exception as exc:
            print(f"[warn] Failed to process {pdf_path.name}: {exc}", file=sys.stderr)
            continue
        new_readings.append(reading)
        processed_hashes.add(digest)
        files_state[digest] = {
            "source_file": pdf_path.name,
            "file_size": reading["file_size"],
            "file_mtime": reading["file_mtime"],
            "processed_at": reading["processed_at"],
            "reading_id": reading["id"],
        }
        known_hashes.add(digest)
        if len(new_readings) >= args.max_new:
            break

    if not new_readings:
        print("[info] No new local PDFs found.")
    else:
        readings = new_readings + [
            item for item in readings
            if not isinstance(item, dict) or item.get("sha256") not in processed_hashes
        ]
        readings.sort(key=lambda item: item.get("processed_at", ""), reverse=True)
        save_json(readings_path, readings)
        verb = "Refreshed" if args.refresh_existing else "Added"
        print(f"[info] {verb} {len(new_readings)} local reading notes.")

    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_json(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
