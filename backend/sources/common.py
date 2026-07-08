"""Shared helpers: JATS full-text XML parsing (PubMed Central, Europe PMC) and retrying requests
against free/anonymous-tier APIs (Semantic Scholar, OpenAlex) that transiently 429/503 under load."""
import time
import xml.etree.ElementTree as ET

import requests

TARGET_SECTIONS = {"RESULT", "DISCUSSION", "CONCLUSION", "METHOD", "FINDING"}
_RETRY_STATUS = {429, 503}


def request_with_retry(method: str, url: str, *, retries: int = 2, backoff: float = 1.5, **kwargs) -> requests.Response:
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code in _RETRY_STATUS and attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            last_exc = e
            if e.response is not None and e.response.status_code in _RETRY_STATUS and attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
    raise last_exc


def get_text(el) -> str:
    return " ".join(el.itertext()).strip()


def truncate(text: str, max_chars: int = 1500) -> str:
    return text[:max_chars] + "..." if len(text) > max_chars else text


def parse_jats_xml(label: str, xml_text: str) -> str:
    """Parse a JATS article XML blob into a readable text summary (title, abstract, key sections)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return f"{label}: XML parse error — {e}"

    parts = [f"=== {label} ==="]
    title_el = root.find(".//article-title")
    if title_el is not None:
        parts.append(f"Title: {get_text(title_el)}")

    abstract_el = root.find(".//abstract")
    if abstract_el is not None:
        parts.append(f"Abstract: {truncate(get_text(abstract_el), 800)}")

    body = root.find(".//body")
    if body is not None:
        for sec in body.findall(".//sec"):
            sec_title_el = sec.find("title")
            if sec_title_el is None:
                continue
            sec_title = get_text(sec_title_el)
            if not any(kw in sec_title.upper() for kw in TARGET_SECTIONS):
                continue
            paras = sec.findall("p")
            sec_text = " ".join(get_text(p) for p in paras)
            if sec_text:
                parts.append(f"\n{sec_title}:\n{truncate(sec_text, 1500)}")

    return "\n".join(parts)
