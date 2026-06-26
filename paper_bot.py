#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily Medical Imaging AI paper digest bot.

The bot searches PubMed, arXiv, Semantic Scholar, and Crossref, scores papers
against the research profile in config.yaml, and sends an email digest.
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
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import feedparser
import requests
import yaml


DEFAULT_MAIL_TO = "dlmu.p.l.zhu@gmail.com"
STATE_KEEP_LIMIT = 3000


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
    reasons: List[str] = field(default_factory=list)
    citation_count: Optional[int] = None
    influential_citation_count: Optional[int] = None
    venue: Optional[str] = None
    tldr: Optional[str] = None
    ai_summary: Optional[str] = None
    pmid: Optional[str] = None
    doi: Optional[str] = None

    def uid(self) -> str:
        for key in self.dedupe_keys():
            return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return hashlib.sha256(self.title.encode("utf-8")).hexdigest()[:16]

    def dedupe_keys(self) -> List[str]:
        keys = []
        doi = normalize_doi(self.doi)
        pmid = normalize_pmid(self.pmid)
        url = normalize_url(self.url)
        title = normalize_title(self.title)
        if doi:
            keys.append(f"doi:{doi}")
        if pmid:
            keys.append(f"pmid:{pmid}")
        if url:
            keys.append(f"url:{url}")
        if title:
            keys.append(f"title:{title}")
        return keys


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg:
        raise ValueError("config.yaml is empty.")
    cfg.setdefault("state_path", "data/sent_papers.json")
    cfg.setdefault("email", {})
    cfg["email"].setdefault("to", DEFAULT_MAIL_TO)
    return cfg


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()


def strip_html(value: Any) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return clean_text(text)


def text_of(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return clean_text(" ".join(elem.itertext()))


def parse_date(value: str | None) -> Optional[dt.date]:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        return dt.date(int(text), 1, 1)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return dt.date.fromisoformat(text[:10])
    except Exception:
        return None


def pubmed_date_to_iso(year: str = "", month: str = "", day: str = "") -> str:
    month_map = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
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
    try:
        return dt.date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ""


def within_lookback(date_str: str, lookback_days: int) -> bool:
    parsed = parse_date(date_str)
    if not parsed:
        return True
    today_utc = dt.datetime.now(dt.timezone.utc).date()
    return parsed >= today_utc - dt.timedelta(days=lookback_days)


def normalize_doi(value: str | None) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text.strip().rstrip(".")


def normalize_pmid(value: str | None) -> str:
    return re.sub(r"\D+", "", clean_text(value))


def normalize_url(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        query = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
        return urllib.parse.urlunsplit((scheme, netloc, path, urllib.parse.urlencode(query), ""))
    except Exception:
        return text.lower().rstrip("/")


def normalize_title(value: str | None) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:180]


def contains_term(text: str, term: str) -> bool:
    term_l = term.lower().strip()
    if not term_l:
        return False
    if re.fullmatch(r"[a-z0-9]+", term_l) and len(term_l) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(term_l)}(?![a-z0-9])", text) is not None
    return term_l in text


def requests_get_json(
    url: str,
    headers: Dict[str, str] | None = None,
    params: Dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    response = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after", "5")
        try:
            sleep_seconds = min(int(float(retry_after)), 30)
        except ValueError:
            sleep_seconds = 5
        time.sleep(sleep_seconds)
        response = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def requests_get_text(
    url: str,
    headers: Dict[str, str] | None = None,
    params: Dict[str, Any] | None = None,
    timeout: int = 30,
) -> str:
    response = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after", "5")
        try:
            sleep_seconds = min(int(float(retry_after)), 30)
        except ValueError:
            sleep_seconds = 5
        time.sleep(sleep_seconds)
        response = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    response.raise_for_status()
    return response.text


def date_parts_to_iso(parts: Any) -> str:
    try:
        values = parts.get("date-parts", [[]])[0]
        if not values:
            return ""
        year = int(values[0])
        month = int(values[1]) if len(values) > 1 else 1
        day = int(values[2]) if len(values) > 2 else 1
        return dt.date(year, month, day).isoformat()
    except Exception:
        return ""


def resolve_mail_to(cfg: Dict[str, Any]) -> str:
    return os.getenv("MAIL_TO") or cfg.get("email", {}).get("to") or DEFAULT_MAIL_TO


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
        chunk = journals[i : i + chunk_size]
        journal_block = " OR ".join(f'"{journal}"[Journal]' for journal in chunk)
        queries.append(f"({journal_block}) AND ({topic_block})")
    return queries


def fetch_pubmed(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("pubmed", {})
    if not source_cfg.get("enabled", True):
        print("[info] PubMed disabled by config.")
        return []

    profile = cfg.get("research_profile", {})
    queries = list(profile.get("pubmed_queries") or profile.get("queries") or [])
    queries.extend(build_pubmed_top_journal_queries(cfg))
    if not queries:
        return []

    retmax = int(source_cfg.get("max_results_per_query", 25))
    lookback_days = int(cfg.get("lookback_days", 14))
    today = dt.datetime.now(dt.timezone.utc).date()
    mindate = (today - dt.timedelta(days=lookback_days)).strftime("%Y/%m/%d")
    maxdate = today.strftime("%Y/%m/%d")

    api_key = os.getenv("NCBI_API_KEY")
    email = os.getenv("NCBI_EMAIL") or source_cfg.get("email") or resolve_mail_to(cfg)
    tool = source_cfg.get("tool", "medical-ai-paper-digest-bot")
    sleep_seconds = float(source_cfg.get("sleep_seconds", 0.35 if api_key else 0.55))

    base_params = {"tool": tool}
    if email:
        base_params["email"] = email
    if api_key:
        base_params["api_key"] = api_key

    papers: List[Paper] = []
    for query in queries:
        esearch_params = {
            **base_params,
            "db": "pubmed",
            "term": query,
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
        except Exception as exc:
            print(f"[warn] PubMed esearch failed for {query!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_seconds)
            continue

        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            time.sleep(sleep_seconds)
            continue

        efetch_params = {**base_params, "db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
        try:
            xml_text = requests_get_text(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params=efetch_params,
            )
            root = ET.fromstring(xml_text)
        except Exception as exc:
            print(f"[warn] PubMed efetch/XML failed for {query!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_seconds)
            continue

        for article in root.findall(".//PubmedArticle"):
            med = article.find("./MedlineCitation")
            art = article.find("./MedlineCitation/Article")
            if med is None or art is None:
                continue

            pmid = text_of(med.find("./PMID"))
            title = text_of(art.find("./ArticleTitle"))
            if not title:
                continue

            abstract_parts = []
            for part in art.findall("./Abstract/AbstractText"):
                label = clean_text(part.attrib.get("Label"))
                body = text_of(part)
                abstract_parts.append(f"{label}: {body}" if label and body else body)
            abstract = clean_text(" ".join(abstract_parts))

            journal_title = text_of(art.find("./Journal/Title"))
            iso_abbrev = text_of(art.find("./Journal/ISOAbbreviation"))
            venue = iso_abbrev or journal_title

            article_date = art.find("./ArticleDate")
            if article_date is not None:
                published = pubmed_date_to_iso(
                    text_of(article_date.find("./Year")),
                    text_of(article_date.find("./Month")),
                    text_of(article_date.find("./Day")),
                )
            else:
                pub_date = art.find("./Journal/JournalIssue/PubDate")
                medline_date = text_of(pub_date.find("./MedlineDate")) if pub_date is not None else ""
                medline_year = re.search(r"\d{4}", medline_date)
                pub_year = text_of(pub_date.find("./Year")) if pub_date is not None else ""
                if not pub_year and medline_year:
                    pub_year = medline_year.group(0)
                published = pubmed_date_to_iso(
                    pub_year,
                    text_of(pub_date.find("./Month")) if pub_date is not None else "",
                    text_of(pub_date.find("./Day")) if pub_date is not None else "",
                )

            authors = []
            for author in art.findall("./AuthorList/Author")[:8]:
                last = text_of(author.find("./LastName"))
                fore = text_of(author.find("./ForeName"))
                collective = text_of(author.find("./CollectiveName"))
                name = clean_text(f"{fore} {last}") if last else collective
                if name:
                    authors.append(name)

            doi = ""
            for article_id in article.findall(".//ArticleId"):
                if article_id.attrib.get("IdType", "").lower() == "doi":
                    doi = text_of(article_id)
                    break

            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else "")
            papers.append(
                Paper(
                    source="PubMed",
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    url=url,
                    published_date=published,
                    query=query,
                    venue=venue,
                    pmid=pmid,
                    doi=doi,
                )
            )
        time.sleep(sleep_seconds)
    return papers


def build_arxiv_query(query: str, categories: List[str] | None = None) -> str:
    terms = [term for term in re.split(r"\s+", query.strip()) if len(term) > 1]
    if not terms:
        terms = [query.strip()]
    term_query = "+AND+".join(f'all:"{term}"' for term in terms[:7])
    if categories:
        category_query = "+OR+".join(f"cat:{category}" for category in categories)
        return f"({term_query})+AND+({category_query})"
    return term_query


def fetch_arxiv(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("arxiv", {})
    if not source_cfg.get("enabled", True):
        print("[info] arXiv disabled by config.")
        return []

    profile = cfg.get("research_profile", {})
    queries = profile.get("arxiv_queries") or profile.get("queries") or []
    max_results = int(source_cfg.get("max_results_per_query", 25))
    categories = source_cfg.get("categories", [])
    lookback_days = int(cfg.get("lookback_days", 14))
    sleep_seconds = float(source_cfg.get("sleep_seconds", 3.1))

    papers: List[Paper] = []
    for query in queries:
        params = {
            "search_query": build_arxiv_query(query, categories=categories),
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params, safe=':+()"')
        try:
            feed = feedparser.parse(url)
            if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
                raise RuntimeError(getattr(feed, "bozo_exception", "unknown feed parse error"))
        except Exception as exc:
            print(f"[warn] arXiv query failed for {query!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_seconds)
            continue

        for entry in feed.entries:
            title = clean_text(entry.get("title"))
            if not title:
                continue
            abstract = clean_text(entry.get("summary"))
            paper_url = clean_text(entry.get("link"))
            published_raw = clean_text(entry.get("published"))
            if not within_lookback(published_raw, lookback_days):
                continue
            published_date = parse_date(published_raw)
            authors = [clean_text(author.get("name")) for author in entry.get("authors", []) if clean_text(author.get("name"))]
            papers.append(
                Paper(
                    source="arXiv",
                    title=title,
                    authors=authors[:8],
                    abstract=abstract,
                    url=paper_url,
                    published_date=published_date.isoformat() if published_date else published_raw[:10],
                    query=query,
                    venue="arXiv",
                    doi=clean_text(entry.get("arxiv_doi")),
                )
            )
        time.sleep(sleep_seconds)
    return papers


def fetch_semantic_scholar(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("semantic_scholar", {})
    if not source_cfg.get("enabled", True):
        print("[info] Semantic Scholar disabled by config.")
        return []

    profile = cfg.get("research_profile", {})
    queries = profile.get("semantic_scholar_queries") or profile.get("queries") or []
    max_results = int(source_cfg.get("max_results_per_query", 20))
    fields = (
        "title,abstract,authors,year,venue,url,publicationDate,citationCount,"
        "influentialCitationCount,tldr,externalIds,publicationTypes,journal"
    )
    headers = {"User-Agent": "daily-medical-ai-paper-digest-bot/1.2"}
    api_key = os.getenv("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    lookback_days = int(cfg.get("lookback_days", 14))
    today_utc = dt.datetime.now(dt.timezone.utc).date()
    start_year = today_utc.year - (1 if today_utc.timetuple().tm_yday <= lookback_days + 2 else 0)
    year_param = f"{start_year}-"
    sleep_seconds = float(source_cfg.get("sleep_seconds", 1.2))

    papers: List[Paper] = []
    for query in queries:
        params = {"query": query, "limit": max_results, "fields": fields, "year": year_param}
        try:
            data = requests_get_json(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                headers=headers,
                params=params,
            )
        except Exception as exc:
            print(f"[warn] Semantic Scholar query failed for {query!r}: {exc}", file=sys.stderr)
            time.sleep(sleep_seconds)
            continue

        for item in data.get("data", []):
            title = clean_text(item.get("title"))
            if not title:
                continue
            abstract = clean_text(item.get("abstract"))
            published = clean_text(item.get("publicationDate") or str(item.get("year") or ""))
            if published and not re.fullmatch(r"\d{4}", published) and not within_lookback(published, lookback_days):
                continue

            authors = [clean_text(author.get("name")) for author in item.get("authors", [])[:8]]
            tldr_obj = item.get("tldr") or {}
            external = item.get("externalIds") or {}
            journal = item.get("journal") or {}
            journal_name = clean_text(journal.get("name")) if isinstance(journal, dict) else ""
            venue = clean_text(item.get("venue")) or journal_name
            doi = clean_text(external.get("DOI")) if isinstance(external, dict) else ""
            url = clean_text(item.get("url")) or (f"https://doi.org/{doi}" if doi else "")

            papers.append(
                Paper(
                    source="Semantic Scholar",
                    title=title,
                    authors=[author for author in authors if author],
                    abstract=abstract,
                    url=url,
                    published_date=published[:10] if published else "",
                    query=query,
                    citation_count=item.get("citationCount"),
                    influential_citation_count=item.get("influentialCitationCount"),
                    venue=venue,
                    tldr=clean_text(tldr_obj.get("text")) if isinstance(tldr_obj, dict) else None,
                    doi=doi,
                )
            )
        time.sleep(sleep_seconds)
    return papers


def fetch_crossref_top_journals(cfg: Dict[str, Any]) -> List[Paper]:
    source_cfg = cfg.get("sources", {}).get("crossref_top_journals", {})
    if not source_cfg.get("enabled", True):
        print("[info] Crossref top journals disabled by config.")
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
    sleep_seconds = float(source_cfg.get("sleep_seconds", 1.0))

    mailto = os.getenv("CROSSREF_MAILTO") or os.getenv("NCBI_EMAIL") or resolve_mail_to(cfg)
    headers = {
        "User-Agent": (
            f"medical-ai-paper-digest-bot/1.2 (mailto:{mailto})"
            if mailto
            else "medical-ai-paper-digest-bot/1.2"
        )
    }

    papers: List[Paper] = []
    calls = 0
    for journal in journals:
        for topic_query in topic_queries:
            if calls >= max_calls:
                print(f"[warn] Crossref max_calls={max_calls} reached; remaining journal queries skipped.", file=sys.stderr)
                return papers
            calls += 1
            params = {
                "query.container-title": journal,
                "query.bibliographic": topic_query,
                "filter": f"type:journal-article,from-pub-date:{from_date},until-pub-date:{until_date}",
                "sort": "published",
                "order": "desc",
                "rows": rows,
                "select": "DOI,title,container-title,published-print,published-online,published,author,abstract,URL,issued,publisher,subject",
            }
            if mailto:
                params["mailto"] = mailto

            try:
                data = requests_get_json("https://api.crossref.org/works", headers=headers, params=params)
            except Exception as exc:
                print(f"[warn] Crossref query failed for {journal!r} / {topic_query!r}: {exc}", file=sys.stderr)
                time.sleep(sleep_seconds)
                continue

            for item in data.get("message", {}).get("items", []):
                title_list = item.get("title") or []
                title = clean_text(title_list[0] if title_list else "")
                if not title:
                    continue

                containers = item.get("container-title") or []
                venue = clean_text(containers[0] if containers else journal)
                abstract = strip_html(item.get("abstract"))
                published = (
                    date_parts_to_iso(item.get("published-online"))
                    or date_parts_to_iso(item.get("published-print"))
                    or date_parts_to_iso(item.get("published"))
                    or date_parts_to_iso(item.get("issued"))
                )
                if published and not within_lookback(published, lookback_days):
                    continue

                authors = []
                for author in (item.get("author") or [])[:8]:
                    given = clean_text(author.get("given"))
                    family = clean_text(author.get("family"))
                    name = clean_text(f"{given} {family}") or clean_text(author.get("name"))
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
                        query=f"{journal} / {topic_query}",
                        venue=venue,
                        doi=doi,
                    )
                )
            time.sleep(sleep_seconds)
    return papers


def add_keyword_scores(
    text_title: str,
    text_all: str,
    weights: Dict[str, Any],
    multiplier_title: float = 1.5,
) -> tuple[float, List[str]]:
    score = 0.0
    reasons = []
    for keyword, weight in weights.items():
        try:
            numeric_weight = float(weight)
        except Exception:
            continue
        if contains_term(text_title, keyword):
            score += numeric_weight * multiplier_title
            reasons.append(f"title:{keyword}")
        elif contains_term(text_all, keyword):
            score += numeric_weight
            reasons.append(keyword)
    return score, reasons


def score_paper(paper: Paper, cfg: Dict[str, Any]) -> Paper:
    scoring = cfg.get("scoring", {})
    keyword_weights = scoring.get("keyword_weights", {})
    focus_weights = scoring.get("brain_neuro_focus_weights", {})
    venue_boosts = scoring.get("top_venue_boosts", {})
    exclude_keywords = [str(keyword).lower() for keyword in scoring.get("exclude_keywords", [])]
    soft_must_have_any = [str(keyword).lower() for keyword in scoring.get("soft_must_have_any", [])]

    text_title = (paper.title or "").lower()
    text_all = " ".join(
        [paper.title or "", paper.abstract or "", paper.tldr or "", paper.venue or "", paper.query or ""]
    ).lower()
    venue_text = (paper.venue or "").lower()

    score = 0.0
    reasons: List[str] = []

    keyword_score, keyword_reasons = add_keyword_scores(text_title, text_all, keyword_weights)
    score += keyword_score
    reasons.extend(keyword_reasons)

    focus_score, focus_reasons = add_keyword_scores(text_title, text_all, focus_weights, multiplier_title=1.8)
    score += focus_score
    reasons.extend(f"focus:{reason}" for reason in focus_reasons)

    for pattern, boost in venue_boosts.items():
        pattern_l = str(pattern).lower()
        if pattern_l in venue_text or pattern_l in text_title:
            score += float(boost)
            reasons.append(f"venue:{pattern}")

    for keyword in exclude_keywords:
        if keyword and keyword in text_all:
            score -= float(scoring.get("exclude_penalty", 5))
            reasons.append(f"exclude:{keyword}")

    if soft_must_have_any and not any(contains_term(text_all, keyword) for keyword in soft_must_have_any):
        score -= float(scoring.get("soft_must_have_penalty", 3))
        reasons.append("no-brain/neuro-soft-focus")

    published = parse_date(paper.published_date)
    if published:
        days_old = (dt.datetime.now(dt.timezone.utc).date() - published).days
        if days_old <= 3:
            score += float(scoring.get("fresh_0_3_days_boost", 2))
            reasons.append("fresh<=3d")
        elif days_old <= 14:
            score += float(scoring.get("fresh_4_14_days_boost", 1))
            reasons.append("fresh<=14d")

    if paper.citation_count and paper.citation_count >= scoring.get("citation_boost_threshold", 30):
        score += float(scoring.get("citation_boost", 1))
        reasons.append("cited")
    if (
        paper.influential_citation_count
        and paper.influential_citation_count >= scoring.get("influential_citation_boost_threshold", 5)
    ):
        score += float(scoring.get("influential_citation_boost", 1.5))
        reasons.append("influential-cited")

    paper.score = round(score, 2)
    paper.reasons = compact_list(reasons, limit=12)
    return paper


def compact_list(values: Iterable[str], limit: int | None = None) -> List[str]:
    seen = set()
    compacted = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        compacted.append(value)
        if limit and len(compacted) >= limit:
            break
    return compacted


def dedupe(papers: Iterable[Paper]) -> List[Paper]:
    seen = set()
    out = []
    for paper in papers:
        keys = paper.dedupe_keys()
        if not keys:
            continue
        if any(key in seen for key in keys):
            continue
        seen.update(keys)
        out.append(paper)
    return out


def new_state() -> Dict[str, Any]:
    return {"sent_ids": {}, "sent_keys": {}, "updated_at": None}


def load_state(path: str) -> Dict[str, Any]:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if not state_path.exists():
        state = new_state()
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] Could not read {state_path}: {exc}; starting with empty sent state.", file=sys.stderr)
        state = new_state()
    if not isinstance(state, dict):
        state = new_state()
    state.setdefault("sent_ids", {})
    state.setdefault("sent_keys", {})
    return state


def save_state(path: str, state: Dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def state_keys_from_records(state: Dict[str, Any]) -> set[str]:
    sent_keys = set(state.get("sent_keys", {}).keys())
    for record in state.get("sent_ids", {}).values():
        if not isinstance(record, dict):
            continue
        temp_paper = Paper(
            source=str(record.get("source") or ""),
            title=str(record.get("title") or ""),
            authors=[],
            abstract="",
            url=str(record.get("url") or ""),
            published_date="",
            query="",
            venue=str(record.get("venue") or ""),
            doi=str(record.get("doi") or ""),
            pmid=str(record.get("pmid") or ""),
        )
        sent_keys.update(temp_paper.dedupe_keys())
    return sent_keys


def already_sent(paper: Paper, state: Dict[str, Any], sent_keys: set[str]) -> bool:
    sent_ids = state.get("sent_ids", {})
    return paper.uid() in sent_ids or any(key in sent_keys for key in paper.dedupe_keys())


def mark_sent(papers: List[Paper], state: Dict[str, Any]) -> None:
    sent_ids = state.setdefault("sent_ids", {})
    sent_keys = state.setdefault("sent_keys", {})
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for paper in papers:
        uid = paper.uid()
        sent_ids[uid] = {
            "title": paper.title,
            "url": paper.url,
            "doi": normalize_doi(paper.doi),
            "pmid": normalize_pmid(paper.pmid),
            "venue": paper.venue,
            "source": paper.source,
            "sent_at": now,
        }
        for key in paper.dedupe_keys():
            sent_keys[key] = uid

    if len(sent_ids) > STATE_KEEP_LIMIT:
        keep_ids = dict(list(sent_ids.items())[-STATE_KEEP_LIMIT:])
        keep_uid_set = set(keep_ids)
        state["sent_ids"] = keep_ids
        state["sent_keys"] = {key: uid for key, uid in sent_keys.items() if uid in keep_uid_set}


def fallback_summary(paper: Paper) -> str:
    summary = clean_text(paper.tldr or paper.abstract or "")
    if len(summary) > 420:
        summary = summary[:420].rstrip() + "..."
    return summary or "No abstract available."


def summarize_with_openai(papers: List[Paper], cfg: Dict[str, Any]) -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model or not papers:
        for paper in papers:
            paper.ai_summary = fallback_summary(paper)
        return

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
    except Exception as exc:
        print(f"[warn] OpenAI SDK unavailable, falling back to abstracts: {exc}", file=sys.stderr)
        for paper in papers:
            paper.ai_summary = fallback_summary(paper)
        return

    max_ai = int(cfg.get("email", {}).get("max_ai_summaries", 10))
    profile_name = cfg.get("research_profile", {}).get("name", "Medical Imaging AI")
    sleep_seconds = float(cfg.get("openai_sleep_seconds", 0.5))

    for index, paper in enumerate(papers):
        if index >= max_ai:
            paper.ai_summary = fallback_summary(paper)
            continue

        prompt = f"""You are a research assistant for {profile_name}.
Summarize the paper in concise Chinese for a medical imaging AI researcher.
Please classify it as one of: brain-gut axis, multi-organ diagnosis, Alzheimer diagnosis,
image synthesis/enhancement, foundation model, radiology/neuroimaging AI, or other.
Include the research problem, data/modality, method, key finding, and why it is worth reading.
Do not invent claims not supported by the abstract.

Title: {paper.title}
Authors: {", ".join(paper.authors[:8])}
Source/Venue: {paper.source} / {paper.venue or ""}
Date: {paper.published_date}
Citations: {paper.citation_count}
Abstract: {(paper.abstract or paper.tldr or "")[:3500]}
"""
        try:
            response = client.responses.create(model=model, input=prompt)
            paper.ai_summary = clean_text(getattr(response, "output_text", "") or fallback_summary(paper))
        except Exception as exc:
            print(f"[warn] OpenAI summary failed for {paper.title[:80]}: {exc}", file=sys.stderr)
            paper.ai_summary = fallback_summary(paper)
        time.sleep(sleep_seconds)


def make_email_html(papers: List[Paper], cfg: Dict[str, Any]) -> str:
    profile = cfg.get("research_profile", {})
    digest_title = f"{profile.get('name', 'Medical Imaging AI')} Daily Paper Radar"
    generated_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M SGT")
    rows = []

    for index, paper in enumerate(papers, 1):
        authors = ", ".join(paper.authors[:8]) or "N/A"
        if len(paper.authors) > 8:
            authors += " et al."
        reasons = ", ".join(paper.reasons or []) or "N/A"
        meta = " | ".join(
            str(value)
            for value in [paper.source, paper.venue, paper.published_date, f"score {paper.score}"]
            if value
        )
        citations = ""
        if paper.citation_count is not None:
            citations = f"Citations: {paper.citation_count}"
            if paper.influential_citation_count is not None:
                citations += f" / Influential: {paper.influential_citation_count}"

        rows.append(
            f"""
        <div style="margin:0 0 22px 0;padding:16px;border:1px solid #ddd;border-radius:8px;">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px;">
            {index}. <a href="{html.escape(paper.url or '#', quote=True)}">{html.escape(paper.title)}</a>
          </div>
          <div style="color:#555;font-size:13px;margin-bottom:8px;">{html.escape(meta)}</div>
          <div style="color:#444;font-size:13px;margin-bottom:8px;"><strong>Authors:</strong> {html.escape(authors)}</div>
          <div style="font-size:14px;line-height:1.55;margin:8px 0;"><strong>Summary:</strong> {html.escape(paper.ai_summary or fallback_summary(paper))}</div>
          <div style="font-size:14px;line-height:1.55;margin:8px 0;"><strong>Abstract:</strong> {html.escape(fallback_summary(paper))}</div>
          <div style="font-size:13px;margin:8px 0;"><strong>Link:</strong> <a href="{html.escape(paper.url or '#', quote=True)}">{html.escape(paper.url or 'N/A')}</a></div>
          <div style="font-size:12px;color:#666;"><strong>Match reasons:</strong> {html.escape(reasons)}. <strong>Score:</strong> {paper.score}. {html.escape(citations)}</div>
        </div>
        """
        )

    if not rows:
        rows.append(
            """
        <div style="margin:0 0 22px 0;padding:16px;border:1px solid #ddd;border-radius:8px;">
          No new papers passed the current score threshold today.
        </div>
        """
        )

    queries = ", ".join(profile.get("queries", [])[:10])
    return f"""<!doctype html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:#222;">
  <h2>{html.escape(digest_title)}</h2>
  <div style="color:#666;margin-bottom:16px;">Generated at: {html.escape(generated_at)}</div>
  <div style="margin-bottom:16px;"><strong>Search focus:</strong> {html.escape(queries)}</div>
  {''.join(rows)}
  <hr/>
  <div style="font-size:12px;color:#777;">
    Generated automatically by Daily Medical Imaging AI Paper Radar. AI summaries are only screening aids;
    verify key claims in the original paper.
  </div>
</body>
</html>"""


def make_email_text(papers: List[Paper], cfg: Dict[str, Any]) -> str:
    profile = cfg.get("research_profile", {})
    lines = [f"{profile.get('name', 'Medical Imaging AI')} Daily Paper Radar", ""]
    if not papers:
        return "\n".join(lines + ["No new papers passed the current score threshold today."])

    for index, paper in enumerate(papers, 1):
        authors = ", ".join(paper.authors[:8]) or "N/A"
        if len(paper.authors) > 8:
            authors += " et al."
        lines.extend(
            [
                f"{index}. {paper.title}",
                f"Source: {paper.source}",
                f"Venue: {paper.venue or 'N/A'}",
                f"Date: {paper.published_date or 'N/A'}",
                f"Authors: {authors}",
                f"Score: {paper.score}",
                f"Match reasons: {', '.join(paper.reasons or []) or 'N/A'}",
                f"Summary: {paper.ai_summary or fallback_summary(paper)}",
                f"Abstract: {fallback_summary(paper)}",
                f"Link: {paper.url or 'N/A'}",
                "",
            ]
        )
    return "\n".join(lines)


def send_email(subject: str, html_body: str, text_body: str, cfg: Dict[str, Any]) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    mail_from = os.getenv("MAIL_FROM") or cfg.get("email", {}).get("from") or user or ""
    mail_to = resolve_mail_to(cfg)
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    if not all([host, port, user, password, mail_from, mail_to]):
        raise RuntimeError(
            "Missing email settings. Required secrets: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD. "
            "MAIL_TO is optional because config.yaml defaults to dlmu.p.l.zhu@gmail.com."
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = mail_to
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.send_message(message)


def safe_fetch(label: str, fetcher: Callable[[Dict[str, Any]], List[Paper]], cfg: Dict[str, Any]) -> List[Paper]:
    print(f"[info] Fetching {label}...")
    try:
        papers = fetcher(cfg)
    except Exception as exc:
        print(f"[warn] {label} failed and will be skipped: {exc}", file=sys.stderr)
        return []
    print(f"[info] {label} papers: {len(papers)}")
    return papers


def env_truthy(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "y")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Print digest instead of sending email.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    state_path = cfg.get("state_path", "data/sent_papers.json")
    state = load_state(state_path)

    papers: List[Paper] = []
    for label, fetcher in [
        ("PubMed", fetch_pubmed),
        ("Crossref top journals", fetch_crossref_top_journals),
        ("arXiv", fetch_arxiv),
        ("Semantic Scholar", fetch_semantic_scholar),
    ]:
        papers.extend(safe_fetch(label, fetcher, cfg))

    papers = [score_paper(paper, cfg) for paper in dedupe(papers)]
    min_score = float(cfg.get("scoring", {}).get("min_score", 8))
    papers = [paper for paper in papers if paper.score >= min_score]

    sent_keys = state_keys_from_records(state)
    papers = [paper for paper in papers if not already_sent(paper, state, sent_keys)]
    papers.sort(
        key=lambda paper: (paper.score, parse_date(paper.published_date) or dt.date(1900, 1, 1)),
        reverse=True,
    )
    max_papers = int(cfg.get("email", {}).get("max_papers", 15))
    papers = papers[:max_papers]

    send_empty = bool(cfg.get("email", {}).get("send_empty_digest", True))
    if not papers and not send_empty:
        print("[info] No new papers and send_empty_digest=false. Nothing to send.")
        return 0

    summarize_with_openai(papers, cfg)

    subject_prefix = cfg.get("email", {}).get("subject_prefix", "Daily Medical Imaging AI Paper Radar")
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    subject = f"{subject_prefix} - {cfg.get('research_profile', {}).get('name', 'Research')} - {today}"
    html_body = make_email_html(papers, cfg)
    text_body = make_email_text(papers, cfg)

    if args.dry_run or env_truthy("DRY_RUN"):
        print("[dry-run] Email will not be sent.")
        print(f"[dry-run] To: {resolve_mail_to(cfg)}")
        print(f"[dry-run] Subject: {subject}")
        print(text_body)
        return 0

    try:
        send_email(subject, html_body, text_body, cfg)
    except Exception as exc:
        print(f"[error] Email send failed; sent state was not updated: {exc}", file=sys.stderr)
        return 1

    print(f"[info] Sent email with {len(papers)} papers.")
    mark_sent(papers, state)
    save_state(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
