#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Medical-AI Research Paper Digest Bot

Sources:
- PubMed via NCBI E-utilities
- arXiv API via Atom feed
- Semantic Scholar Graph API paper search

Focus:
- Medical imaging + AI
- Brain / neuroimaging priority
- Brain-gut / gut-brain axis
- Multi-organ guided diagnosis
- Alzheimer's disease diagnosis
- Medical image synthesis / enhancement
- Top journals / conferences boosted
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import feedparser
import requests
import yaml


@dataclass
class Paper:
    source: str
    title: str
    authors: List[str]
    abstract: str
    url: str
    published_date: str
    query: str
    score: float = 0.0
    reasons: List[str] = None
    citation_count: Optional[int] = None
    influential_citation_count: Optional[int] = None
    venue: Optional[str] = None
    tldr: Optional[str] = None
    ai_summary: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None

    def uid(self) -> str:
        key = self.doi or self.pmid or self.url or self.title.lower().strip()
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        raise ValueError("config.yaml is empty.")
    return cfg


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def text_of(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return clean_text(" ".join(elem.itertext()))


def parse_date(s: str | None) -> Optional[dt.date]:
    if not s:
        return None
    s = str(s).strip()
    if re.fullmatch(r"\d{4}", s):
        return dt.date(int(s), 1, 1)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def pubmed_date_to_iso(year: str = "", month: str = "", day: str = "") -> str:
    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    year = clean_text(year)
    month = clean_text(month)
    day = clean_text(day)
    if not year:
        return ""
    if month:
        if not month.isdigit():
            month = month_map.get(month[:3].lower(), "01")
        month = month.zfill(2)
    else:
        month = "01"
    day = (day or "01").zfill(2)
    return f"{year}-{month}-{day}"


def within_lookback(date_str: str, lookback_days: int) -> bool:
    d = parse_date(date_str)
    if not d:
        return True
    today_utc = dt.datetime.now(dt.timezone.utc).date()
    return d >= today_utc - dt.timedelta(days=lookback_days)


def requests_get_json(url: str, headers: Dict[str, str] | None = None, params: Dict[str, Any] | None = None, timeout: int = 30) -> Any:
    resp = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("retry-after", "5"))
        time.sleep(min(retry_after, 30))
        resp = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def requests_get_text(url: str, headers: Dict[str, str] | None = None, params: Dict[str, Any] | None = None, timeout: int = 30) -> str:
    resp = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("retry-after", "5"))
        time.sleep(min(retry_after, 30))
        resp = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def date_parts_to_iso(parts: Any) -> str:
    try:
        p = parts.get("date-parts", [[]])[0]
        if not p:
            return ""
        y = int(p[0])
        m = int(p[1]) if len(p) > 1 else 1
        d = int(p[2]) if len(p) > 2 else 1
        return dt.date(y, m, d).isoformat()
    except Exception:
        return ""


def build_pubmed_top_journal_queries(cfg: Dict[str, Any]) -> List[str]:
    source_cfg = cfg.get("sources", {}).get("pubmed", {})
    if not source_cfg.get("top_journal_family_search", True):
        return []

    journals = cfg.get("top_journal_families", {}).get("pubmed_journals", [])
    topic_block = cfg.get("top_journal_families", {}).get("pubmed_topic_block", "")
    chunk_size = int(source_cfg.get("top_journal_chunk_size", 18))

    if not journals or not topic_block:
        return []

    queries = []
    for i in range(0, len(journals), chunk_size):
        chunk = journals[i:i + chunk_size]
        journal_block = " OR ".join([f'"{j}"[Journal]' for j in chunk])
        queries.append(f"({journal_block}) AND ({topic_block})")
    return queries


def fetch_crossref_top_journals(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("crossref_top_journals", {})
    if not source_cfg.get("enabled", True):
        return []

    journals = cfg.get("top_journal_families", {}).get("crossref_journals", [])
    topic_queries = cfg.get("top_journal_families", {}).get("crossref_topic_queries", [])
    if not journals or not topic_queries:
        return []

    rows = int(source_cfg.get("rows_per_query", 5))
    max_calls = int(source_cfg.get("max_calls", 90))
    lookback_days = int(cfg.get("lookback_days", 14))
    today = dt.datetime.now(dt.timezone.utc).date()
    from_date = (today - dt.timedelta(days=lookback_days)).isoformat()
    until_date = today.isoformat()

    mailto = (
        os.getenv("CROSSREF_MAILTO")
        or os.getenv("NCBI_EMAIL")
        or cfg.get("email", {}).get("to", "")
        or ""
    )
    headers = {
        "User-Agent": f"medical-ai-paper-digest-bot/1.1 (mailto:{mailto})" if mailto else "medical-ai-paper-digest-bot/1.1"
    }

    papers: List[Paper] = []
    calls = 0

    for journal in journals:
        for tq in topic_queries:
            if calls >= max_calls:
                print(f"[warn] Crossref max_calls={max_calls} reached; remaining journal queries skipped.", file=sys.stderr)
                return papers
            calls += 1

            params = {
                "query.container-title": journal,
                "query.bibliographic": tq,
                "filter": f"type:journal-article,from-pub-date:{from_date},until-pub-date:{until_date}",
                "sort": "published",
                "order": "desc",
                "rows": rows,
                "select": "DOI,title,container-title,published-print,published-online,published,author,abstract,URL,issued,publisher,subject",
                "mailto": mailto,
            }
            # Empty mailto can be accepted but is unnecessary.
            if not mailto:
                params.pop("mailto", None)

            try:
                data = requests_get_json("https://api.crossref.org/works", headers=headers, params=params)
            except Exception as e:
                print(f"[warn] Crossref query failed for {journal!r} / {tq!r}: {e}", file=sys.stderr)
                continue

            for item in data.get("message", {}).get("items", []):
                title_list = item.get("title") or []
                title = clean_text(title_list[0] if title_list else "")
                if not title:
                    continue

                containers = item.get("container-title") or []
                venue = clean_text(containers[0] if containers else journal)
                abstract = clean_text(re.sub("<[^<]+?>", " ", item.get("abstract", "") or ""))

                published = (
                    date_parts_to_iso(item.get("published-online"))
                    or date_parts_to_iso(item.get("published-print"))
                    or date_parts_to_iso(item.get("published"))
                    or date_parts_to_iso(item.get("issued"))
                )
                if published and not within_lookback(published, lookback_days):
                    continue

                authors = []
                for a in (item.get("author") or [])[:8]:
                    given = clean_text(a.get("given"))
                    family = clean_text(a.get("family"))
                    name = clean_text(f"{given} {family}") or clean_text(a.get("name"))
                    if name:
                        authors.append(name)

                doi = clean_text(item.get("DOI"))
                url = clean_text(item.get("URL")) or (f"https://doi.org/{doi}" if doi else "")

                papers.append(
                    Paper(
                        source="Crossref Top Journals",
                        title=title,
                        authors=authors,
                        abstract=abstract,
                        url=url,
                        published_date=published,
                        query=f"{journal} / {tq}",
                        venue=venue,
                        doi=doi,
                    )
                )

            time.sleep(float(source_cfg.get("sleep_seconds", 1.0)))

    return papers


def fetch_pubmed(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("pubmed", {})
    if not source_cfg.get("enabled", True):
        return []

    queries = list(cfg["research_profile"].get("pubmed_queries") or cfg["research_profile"]["queries"])
    queries.extend(build_pubmed_top_journal_queries(cfg))
    retmax = int(source_cfg.get("max_results_per_query", 25))
    lookback_days = int(cfg.get("lookback_days", 14))
    today = dt.datetime.now(dt.timezone.utc).date()
    mindate = (today - dt.timedelta(days=lookback_days)).strftime("%Y/%m/%d")
    maxdate = today.strftime("%Y/%m/%d")

    api_key = os.getenv("NCBI_API_KEY")
    email = os.getenv("NCBI_EMAIL") or source_cfg.get("email", "")
    tool = source_cfg.get("tool", "medical-ai-paper-digest-bot")

    base_params = {"tool": tool}
    if email:
        base_params["email"] = email
    if api_key:
        base_params["api_key"] = api_key

    papers: List[Paper] = []
    for q in queries:
        esearch_params = {
            **base_params,
            "db": "pubmed",
            "term": q,
            "retmode": "json",
            "retmax": retmax,
            "sort": "pub+date",
            "datetype": "pdat",
            "mindate": mindate,
            "maxdate": maxdate,
        }
        try:
            data = requests_get_json(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params=esearch_params,
            )
        except Exception as e:
            print(f"[warn] PubMed esearch failed for {q!r}: {e}", file=sys.stderr)
            continue

        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            time.sleep(float(source_cfg.get("sleep_seconds", 0.35 if api_key else 0.55)))
            continue

        efetch_params = {
            **base_params,
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
        }
        try:
            xml_text = requests_get_text(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params=efetch_params,
            )
        except Exception as e:
            print(f"[warn] PubMed efetch failed for {q!r}: {e}", file=sys.stderr)
            continue

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"[warn] PubMed XML parse failed for {q!r}: {e}", file=sys.stderr)
            continue

        for article in root.findall(".//PubmedArticle"):
            med = article.find("./MedlineCitation")
            art = article.find("./MedlineCitation/Article")
            if med is None or art is None:
                continue

            pmid = text_of(med.find("./PMID"))
            title = text_of(art.find("./ArticleTitle"))
            abstract = clean_text(" ".join(text_of(x) for x in art.findall("./Abstract/AbstractText")))

            journal_title = text_of(art.find("./Journal/Title"))
            iso_abbrev = text_of(art.find("./Journal/ISOAbbreviation"))
            venue = iso_abbrev or journal_title

            # Prefer ArticleDate, then Journal PubDate.
            ad = art.find("./ArticleDate")
            if ad is not None:
                published = pubmed_date_to_iso(text_of(ad.find("./Year")), text_of(ad.find("./Month")), text_of(ad.find("./Day")))
            else:
                pd = art.find("./Journal/JournalIssue/PubDate")
                published = pubmed_date_to_iso(text_of(pd.find("./Year")) if pd is not None else "",
                                               text_of(pd.find("./Month")) if pd is not None else "",
                                               text_of(pd.find("./Day")) if pd is not None else "")

            authors = []
            for a in art.findall("./AuthorList/Author")[:8]:
                last = text_of(a.find("./LastName"))
                fore = text_of(a.find("./ForeName"))
                coll = text_of(a.find("./CollectiveName"))
                name = clean_text(f"{fore} {last}") if last else coll
                if name:
                    authors.append(name)

            doi = ""
            for aid in article.findall(".//ArticleId"):
                if aid.attrib.get("IdType", "").lower() == "doi":
                    doi = text_of(aid)
                    break

            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else "")
            if not title:
                continue

            papers.append(
                Paper(
                    source="PubMed",
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    url=url,
                    published_date=published,
                    query=q,
                    venue=venue,
                    pmid=pmid,
                    doi=doi,
                )
            )

        time.sleep(float(source_cfg.get("sleep_seconds", 0.35 if api_key else 0.55)))
    return papers


def build_arxiv_query(query: str, categories: List[str] | None = None) -> str:
    terms = [t for t in re.split(r"\s+", query.strip()) if len(t) > 1]
    if not terms:
        terms = [query.strip()]
    term_query = "+AND+".join([f'all:"{t}"' for t in terms[:7]])
    if categories:
        cat_query = "+OR+".join([f"cat:{c}" for c in categories])
        return f"({term_query})+AND+({cat_query})"
    return term_query


def fetch_arxiv(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("arxiv", {})
    if not source_cfg.get("enabled", True):
        return []

    max_results = int(source_cfg.get("max_results_per_query", 25))
    categories = source_cfg.get("categories", [])
    queries = cfg["research_profile"].get("arxiv_queries") or cfg["research_profile"]["queries"]
    lookback_days = int(cfg.get("lookback_days", 14))

    papers: List[Paper] = []
    for q in queries:
        arxiv_q = build_arxiv_query(q, categories=categories)
        params = {
            "search_query": arxiv_q,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params, safe=':+()"')
        feed = feedparser.parse(url)

        for entry in feed.entries:
            title = clean_text(entry.get("title"))
            abstract = clean_text(entry.get("summary"))
            url_abs = clean_text(entry.get("link"))
            published = clean_text(entry.get("published"))
            if not within_lookback(published, lookback_days):
                continue
            authors = [clean_text(a.get("name")) for a in entry.get("authors", [])]
            papers.append(
                Paper(
                    source="arXiv",
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    url=url_abs,
                    published_date=(parse_date(published).isoformat() if parse_date(published) else published[:10]),
                    query=q,
                    venue="arXiv",
                )
            )
        time.sleep(float(source_cfg.get("sleep_seconds", 3.1)))
    return papers


def fetch_semantic_scholar(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("semantic_scholar", {})
    if not source_cfg.get("enabled", True):
        return []

    max_results = int(source_cfg.get("max_results_per_query", 20))
    fields = "title,abstract,authors,year,venue,url,publicationDate,citationCount,influentialCitationCount,tldr,externalIds,publicationTypes,journal"
    headers = {"User-Agent": "daily-medical-ai-paper-digest-bot/1.0"}
    api_key = os.getenv("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    lookback_days = int(cfg.get("lookback_days", 14))
    today_utc = dt.datetime.now(dt.timezone.utc).date()
    start_year = today_utc.year - (1 if today_utc.timetuple().tm_yday <= lookback_days + 2 else 0)
    year_param = f"{start_year}-"

    queries = cfg["research_profile"].get("semantic_scholar_queries") or cfg["research_profile"]["queries"]
    papers: List[Paper] = []

    for q in queries:
        params = {"query": q, "limit": max_results, "fields": fields, "year": year_param}
        try:
            data = requests_get_json(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                headers=headers,
                params=params,
            )
        except Exception as e:
            print(f"[warn] Semantic Scholar query failed for {q!r}: {e}", file=sys.stderr)
            continue

        for item in data.get("data", []):
            title = clean_text(item.get("title"))
            abstract = clean_text(item.get("abstract"))
            published = clean_text(item.get("publicationDate") or str(item.get("year") or ""))
            if published and re.fullmatch(r"\d{4}", published):
                pass
            elif published and not within_lookback(published, lookback_days):
                continue

            authors = [clean_text(a.get("name")) for a in item.get("authors", [])[:8]]
            tldr_obj = item.get("tldr") or {}
            external = item.get("externalIds") or {}
            journal = item.get("journal") or {}
            venue = clean_text(item.get("venue") or journal.get("name") if isinstance(journal, dict) else item.get("venue"))
            doi = clean_text(external.get("DOI") if isinstance(external, dict) else "")
            papers.append(
                Paper(
                    source="Semantic Scholar",
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    url=clean_text(item.get("url")) or (f"https://doi.org/{doi}" if doi else ""),
                    published_date=published[:10] if published else "",
                    query=q,
                    citation_count=item.get("citationCount"),
                    influential_citation_count=item.get("influentialCitationCount"),
                    venue=venue,
                    tldr=clean_text(tldr_obj.get("text")) if isinstance(tldr_obj, dict) else None,
                    doi=doi,
                )
            )
        time.sleep(float(source_cfg.get("sleep_seconds", 1.2)))
    return papers


def add_keyword_scores(text_title: str, text_all: str, weights: Dict[str, Any], multiplier_title: float = 1.5) -> tuple[float, List[str]]:
    score = 0.0
    reasons = []
    for kw, weight in weights.items():
        kw_l = kw.lower()
        try:
            w = float(weight)
        except Exception:
            continue
        if kw_l in text_title:
            score += w * multiplier_title
            reasons.append(f"title:{kw}")
        elif kw_l in text_all:
            score += w
            reasons.append(kw)
    return score, reasons


def score_paper(p: Paper, cfg: Dict[str, Any]) -> Paper:
    scoring = cfg.get("scoring", {})
    keyword_weights = scoring.get("keyword_weights", {})
    focus_weights = scoring.get("brain_neuro_focus_weights", {})
    venue_boosts = scoring.get("top_venue_boosts", {})
    exclude = [x.lower() for x in scoring.get("exclude_keywords", [])]
    must_have_any = [x.lower() for x in scoring.get("soft_must_have_any", [])]

    text_title = (p.title or "").lower()
    text_all = " ".join([p.title or "", p.abstract or "", p.tldr or "", p.venue or "", p.query or ""]).lower()
    venue_text = (p.venue or "").lower()

    score = 0.0
    reasons = []

    s, r = add_keyword_scores(text_title, text_all, keyword_weights)
    score += s
    reasons += r

    fs, fr = add_keyword_scores(text_title, text_all, focus_weights, multiplier_title=1.8)
    score += fs
    reasons += [f"focus:{x}" for x in fr]

    for pattern, boost in venue_boosts.items():
        if pattern.lower() in venue_text or pattern.lower() in text_title:
            score += float(boost)
            reasons.append(f"venue:{pattern}")

    for kw in exclude:
        if kw and kw in text_all:
            score -= float(scoring.get("exclude_penalty", 5))
            reasons.append(f"exclude:{kw}")

    if must_have_any and not any(x in text_all for x in must_have_any):
        score -= float(scoring.get("soft_must_have_penalty", 3))
        reasons.append("no-brain/neuro-soft-focus")

    d = parse_date(p.published_date)
    if d:
        days_old = (dt.datetime.now(dt.timezone.utc).date() - d).days
        if days_old <= 3:
            score += float(scoring.get("fresh_0_3_days_boost", 2))
            reasons.append("fresh<=3d")
        elif days_old <= 14:
            score += float(scoring.get("fresh_4_14_days_boost", 1))
            reasons.append("fresh<=14d")

    if p.citation_count and p.citation_count >= scoring.get("citation_boost_threshold", 30):
        score += float(scoring.get("citation_boost", 1))
        reasons.append("cited")
    if p.influential_citation_count and p.influential_citation_count >= scoring.get("influential_citation_boost_threshold", 5):
        score += float(scoring.get("influential_citation_boost", 1.5))
        reasons.append("influential-cited")

    p.score = round(score, 2)
    # Preserve order but remove duplicate reasons.
    seen = set()
    compact_reasons = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            compact_reasons.append(reason)
    p.reasons = compact_reasons[:10]
    return p


def dedupe(papers: Iterable[Paper]) -> List[Paper]:
    seen = set()
    out = []
    for p in papers:
        key = p.uid()
        title_key = re.sub(r"\W+", "", (p.title or "").lower())[:120]
        if key in seen or title_key in seen:
            continue
        seen.add(key)
        seen.add(title_key)
        out.append(p)
    return out


def load_state(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"sent_ids": {}, "updated_at": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"sent_ids": {}, "updated_at": None}


def save_state(path: str, state: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fallback_summary(p: Paper) -> str:
    abstract = p.tldr or p.abstract or ""
    abstract = clean_text(abstract)
    if len(abstract) > 420:
        abstract = abstract[:420].rstrip() + "..."
    return abstract or "暂无摘要。"


def summarize_with_openai(papers: List[Paper], cfg: Dict[str, Any]) -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model or not papers:
        for p in papers:
            p.ai_summary = fallback_summary(p)
        return

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except Exception as e:
        print(f"[warn] OpenAI SDK unavailable, fallback to abstracts: {e}", file=sys.stderr)
        for p in papers:
            p.ai_summary = fallback_summary(p)
        return

    max_ai = int(cfg.get("email", {}).get("max_ai_summaries", 10))
    profile_name = cfg.get("research_profile", {}).get("name", "research profile")

    for i, p in enumerate(papers):
        if i >= max_ai:
            p.ai_summary = fallback_summary(p)
            continue

        prompt = f"""你是医学影像 AI 方向的科研助理。请用中文总结下面论文，聚焦“{profile_name}”。

要求：
1. 先判断它属于哪类：brain-gut axis / multi-organ diagnosis / Alzheimer diagnosis / image synthesis-enhancement / foundation model / other；
2. 用 3-5 句话说明研究问题、数据/模态、方法、核心结论；
3. 单独给出“为什么值得读/是否像顶刊顶会候选”的判断；
4. 不要夸大，不要编造摘要里没有的信息。

标题：{p.title}
作者：{", ".join(p.authors[:8])}
来源：{p.source} / {p.venue or ""}
日期：{p.published_date}
引用：{p.citation_count}
摘要：{p.abstract[:3500] or p.tldr}
"""
        try:
            resp = client.responses.create(model=model, input=prompt)
            p.ai_summary = clean_text(getattr(resp, "output_text", "") or fallback_summary(p))
        except Exception as e:
            print(f"[warn] OpenAI summary failed for {p.title[:60]}: {e}", file=sys.stderr)
            p.ai_summary = fallback_summary(p)
        time.sleep(float(cfg.get("openai_sleep_seconds", 0.5)))


def make_email_html(papers: List[Paper], cfg: Dict[str, Any]) -> str:
    profile = cfg.get("research_profile", {})
    title = f"{profile.get('name', 'Research')}｜每日论文雷达"
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M SGT")

    rows = []
    for idx, p in enumerate(papers, 1):
        authors = ", ".join(p.authors[:8])
        if len(p.authors) > 8:
            authors += " et al."
        reasons = ", ".join(p.reasons or [])
        meta = " · ".join([x for x in [p.source, p.venue, p.published_date, f"score {p.score}"] if x])
        cite = ""
        if p.citation_count is not None:
            cite = f"引用 {p.citation_count}"
            if p.influential_citation_count is not None:
                cite += f" / 重要引用 {p.influential_citation_count}"
        rows.append(f"""
        <div style="margin:0 0 22px 0;padding:16px;border:1px solid #ddd;border-radius:10px;">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px;">
            {idx}. <a href="{html.escape(p.url)}">{html.escape(p.title)}</a>
          </div>
          <div style="color:#666;font-size:13px;margin-bottom:8px;">{html.escape(meta)}</div>
          <div style="color:#444;font-size:13px;margin-bottom:8px;">{html.escape(authors)}</div>
          <p style="font-size:15px;line-height:1.58;margin:8px 0;white-space:pre-wrap;">{html.escape(p.ai_summary or fallback_summary(p))}</p>
          <div style="font-size:12px;color:#777;">匹配原因：{html.escape(reasons or "N/A")} {html.escape(cite)}</div>
        </div>
        """)

    if not rows:
        rows.append("""
        <div style="margin:0 0 22px 0;padding:16px;border:1px solid #ddd;border-radius:10px;">
        今天没有筛选出超过阈值的新论文。可以调低 config.yaml 里的 min_score，或增加 queries。
        </div>
        """)

    queries = ", ".join(profile.get("queries", [])[:10])
    return f"""<!doctype html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:#222;">
  <h2>{html.escape(title)}</h2>
  <div style="color:#666;margin-bottom:16px;">生成时间：{today}</div>
  <div style="margin-bottom:16px;">检索主题：{html.escape(queries)}</div>
  {''.join(rows)}
  <hr/>
  <div style="font-size:12px;color:#777;">
    本邮件由 Daily Medical-AI Research Paper Digest Bot 自动生成。AI 摘要仅作初筛参考，关键结论请以原文为准。
  </div>
</body>
</html>"""


def make_email_text(papers: List[Paper], cfg: Dict[str, Any]) -> str:
    profile = cfg.get("research_profile", {})
    lines = [f"{profile.get('name', 'Research')}｜每日论文雷达", ""]
    if not papers:
        return "\n".join(lines + ["今天没有筛选出超过阈值的新论文。"])
    for idx, p in enumerate(papers, 1):
        lines += [
            f"{idx}. {p.title}",
            f"{p.source} / {p.venue or ''} / {p.published_date} / score {p.score}",
            f"作者：{', '.join(p.authors[:8])}",
            f"摘要：{p.ai_summary or fallback_summary(p)}",
            f"链接：{p.url}",
            f"匹配原因：{', '.join(p.reasons or [])}",
            "",
        ]
    return "\n".join(lines)


def send_email(subject: str, html_body: str, text_body: str, cfg: Dict[str, Any]) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    mail_from = os.getenv("MAIL_FROM") or cfg.get("email", {}).get("from", "") or user or ""
    mail_to = os.getenv("MAIL_TO") or cfg.get("email", {}).get("to", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    if not all([host, port, user, password, mail_from, mail_to]):
        raise RuntimeError(
            "Missing email env vars. Required: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM, MAIL_TO"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.send_message(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="Print digest instead of sending email.")
    args = ap.parse_args()

    cfg = load_config(args.config)
    state_path = cfg.get("state_path", "data/sent_papers.json")
    state = load_state(state_path)

    papers: List[Paper] = []

    print("[info] Fetching PubMed...")
    pubmed = fetch_pubmed(cfg)
    print(f"[info] PubMed papers: {len(pubmed)}")
    papers.extend(pubmed)

    print("[info] Fetching Crossref top journals...")
    crossref = fetch_crossref_top_journals(cfg)
    print(f"[info] Crossref top-journal papers: {len(crossref)}")
    papers.extend(crossref)

    print("[info] Fetching arXiv...")
    arxiv = fetch_arxiv(cfg)
    print(f"[info] arXiv papers: {len(arxiv)}")
    papers.extend(arxiv)

    print("[info] Fetching Semantic Scholar...")
    s2 = fetch_semantic_scholar(cfg)
    print(f"[info] Semantic Scholar papers: {len(s2)}")
    papers.extend(s2)

    papers = [score_paper(p, cfg) for p in dedupe(papers)]
    min_score = float(cfg.get("scoring", {}).get("min_score", 8))
    papers = [p for p in papers if p.score >= min_score]

    sent_ids = state.get("sent_ids", {})
    papers = [p for p in papers if p.uid() not in sent_ids]

    # Sort by score first, then publication date. Freshness is already boosted in score.
    papers.sort(key=lambda p: (p.score, parse_date(p.published_date) or dt.date(1900, 1, 1)), reverse=True)
    max_papers = int(cfg.get("email", {}).get("max_papers", 15))
    papers = papers[:max_papers]

    send_empty = bool(cfg.get("email", {}).get("send_empty_digest", True))
    if not papers and not send_empty:
        print("[info] No new papers and send_empty_digest=false. Nothing to send.")
        save_state(state_path, state)
        return 0

    summarize_with_openai(papers, cfg)

    subject_prefix = cfg.get("email", {}).get("subject_prefix", "每日医学影像AI论文雷达")
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    subject = f"{subject_prefix}｜{cfg.get('research_profile', {}).get('name', 'Research')}｜{today}"

    html_body = make_email_html(papers, cfg)
    text_body = make_email_text(papers, cfg)

    if args.dry_run or os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"):
        print(text_body)
        save_state(state_path, state)
        return 0

    send_email(subject, html_body, text_body, cfg)
    print(f"[info] Sent email with {len(papers)} papers.")

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for p in papers:
        sent_ids[p.uid()] = {"title": p.title, "url": p.url, "sent_at": now, "venue": p.venue, "source": p.source}
    if len(sent_ids) > 3000:
        sent_ids = dict(list(sent_ids.items())[-3000:])
    state["sent_ids"] = sent_ids
    save_state(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
