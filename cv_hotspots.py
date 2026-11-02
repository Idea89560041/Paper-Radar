"""Small, evidence-filtered CV conference reading list from official proceedings."""

import datetime as dt
import re
import sys
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path


class ProceedingsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.meta = {}
        self.abstract = []
        self._link = None
        self._link_text = []
        self._abstract_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self._link = attrs.get("href")
            self._link_text = []
        if tag == "meta":
            name = attrs.get("name") or attrs.get("property")
            if name:
                self.meta.setdefault(name, []).append(attrs.get("content", ""))
        if attrs.get("id") == "abstract":
            self._abstract_depth = 1
        elif self._abstract_depth and tag not in {"br", "img", "meta", "input", "hr"}:
            self._abstract_depth += 1

    def handle_endtag(self, tag):
        if tag == "a" and self._link:
            self.links.append((self._link, " ".join(self._link_text).strip()))
            self._link = None
        if self._abstract_depth:
            self._abstract_depth -= 1

    def handle_data(self, data):
        if self._link:
            self._link_text.append(data.strip())
        if self._abstract_depth:
            self.abstract.append(data.strip())


def canonical_title(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def is_official_paper(url):
    parsed = urllib.parse.urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"openaccess.thecvf.com", "www.ecva.net", "ecva.net"}
        and "/papers/" in parsed.path
        and parsed.path.endswith(".html")
    ) or (
        parsed.scheme == "https" and parsed.hostname == "openaccess.thecvf.com"
        and "/html/" in parsed.path and parsed.path.endswith(".html")
    )


def matching_topic(title, topics):
    text = title.lower()
    for topic in topics:
        if any(term.lower() in text for term in topic["terms"]):
            return topic
    return None


def current_conference_catalogs(year):
    catalogs = [(f"CVPR {year}", f"https://openaccess.thecvf.com/CVPR{year}?day=all")]
    if year % 2:
        catalogs.append((f"ICCV {year}", f"https://openaccess.thecvf.com/ICCV{year}?day=all"))
    else:
        catalogs.append((f"ECCV {year}", "https://www.ecva.net/papers.php"))
    return catalogs


def fetch_cv_hotspots(cfg):
    # Lazy import keeps the main bot's Paper and HTTP helpers shared.
    import paper_bot as bot

    settings = cfg.get("cv_hotspots", {})
    if not settings.get("enabled", False):
        return []
    deadline = time.monotonic() + int(settings.get("max_runtime_seconds", 160))
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    namespace = bot.state_namespace(cfg)
    state = {}
    sent_keys = set()
    if cfg.get("site", {}).get("use_sent_state", True) and Path(cfg.get("state_path", "data/sent_papers.json")).exists():
        state = bot.load_state(cfg.get("state_path", "data/sent_papers.json"))
        sent_keys = bot.state_keys_from_records(state, namespace)
        local_today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
        sent_today = 0
        for record in state.get("sent_ids", {}).values():
            if record.get("source") != "CVF Hot Ideas" or record.get("state_namespace", "") != namespace:
                continue
            try:
                sent_date = dt.datetime.fromisoformat(record["sent_at"]).astimezone(dt.timezone(dt.timedelta(hours=8))).date()
                sent_today += sent_date == local_today
            except (KeyError, ValueError):
                continue
        remaining = max(0, int(cfg.get("site", {}).get("max_cv_hotspots", 2)) - sent_today)
        cfg["_cv_remaining_today"] = remaining
        if not remaining:
            return []
    year = today.year
    catalogs = current_conference_catalogs(year)
    awards = []
    for award_url in settings.get("award_sources", []):
        award_url = award_url.format(year=year)
        if time.monotonic() >= deadline:
            break
        try:
            content = bot.requests_get_text(award_url, timeout=12)
            awards.append((canonical_title(bot.strip_html(content)), award_url))
        except Exception:
            print("[warn] CV award source unavailable; citation evidence still permitted.", file=sys.stderr)

    candidates = {}
    for venue, catalog in catalogs:
        if time.monotonic() >= deadline:
            break
        try:
            parser = ProceedingsParser()
            parser.feed(bot.requests_get_text(catalog, timeout=20))
            conference, conference_year = venue.split()
            for link, title in parser.links:
                url = urllib.parse.urljoin(catalog, link)
                if not is_official_paper(url) or not title:
                    continue
                if conference == "ECCV" and f"eccv_{conference_year}" not in url.lower():
                    continue
                if conference != "ECCV" and f"/{conference}{conference_year}/" not in url:
                    continue
                topic = matching_topic(title, settings.get("topics", []))
                if not topic:
                    continue
                stub = bot.Paper(source="CVF Hot Ideas", title=title, authors=[], abstract="",
                                 url=url, published_date="", query="", venue=venue)
                if sent_keys and bot.already_sent(stub, state, sent_keys, namespace):
                    continue
                title_key = canonical_title(title)
                award = next((url for text, url in awards if len(title_key) > 20 and title_key in text), "")
                candidates[url] = (bool(award), venue, title, topic, award)
        except Exception:
            print(f"[warn] {venue} official proceedings unavailable; continuing.", file=sys.stderr)

    # Award winners go first; evaluate only a small number of other candidates.
    ranked = sorted(candidates.items(), key=lambda item: item[1][0], reverse=True)
    papers = []
    for url, (_, venue, title, topic, award_url) in ranked[:int(settings.get("max_candidates", 12))]:
        if time.monotonic() >= deadline:
            break
        citations = 0
        evidence = f"Official award: {award_url}" if award_url else ""
        try:
            data = bot.requests_get_json("https://api.openalex.org/works", params={"search": title, "per-page": 3}, timeout=10)
            match = next((work for work in data.get("results", [])
                          if canonical_title(work.get("display_name", "")) == canonical_title(title)), None)
            if match:
                citations = int(match.get("cited_by_count", 0))
                if citations >= int(settings.get("min_citations", 100)):
                    evidence = f"OpenAlex citations={citations}: {match['id']}" + (f"; {evidence}" if evidence else "")
        except Exception:
            pass
        if not evidence:
            continue
        try:
            parser = ProceedingsParser()
            parser.feed(bot.requests_get_text(url, timeout=12))
            abstract = bot.clean_text(" ".join(parser.abstract))
            if not abstract:
                continue
            authors = parser.meta.get("citation_author", [])[:8]
            date_value = (parser.meta.get("citation_publication_date") or [f"{venue.split()[-1]}-01-01"])[0].replace("/", "-")
            date = bot.parse_date(date_value)
            if not date or date > today or date.year != year:
                continue
            paper = bot.Paper(
                source="CVF Hot Ideas", title=title, authors=authors, abstract=abstract,
                url=url, published_date=date_value if re.fullmatch(r"\d{4}", date_value) else date.isoformat(),
                query=topic["name"], venue=venue,
                citation_count=citations, cv_hotspot=True, popularity_evidence=evidence,
                ai_summary=f"迁移想法（待验证）：{topic['medical_transfer']}",
            )
            papers.append(paper)
        except Exception:
            print("[warn] CV paper metadata unavailable; candidate skipped.", file=sys.stderr)
    print(f"[info] CV hotspot evidence filter: {len(candidates)} topic candidates, {len(papers)} verified popular papers.", flush=True)
    return papers
