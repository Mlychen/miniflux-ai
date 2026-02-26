import hashlib
import json
import re
import threading
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ratelimit import limits, sleep_and_retry

from common.entries_repository import EntriesRepository
from core.entry_rendering import build_summary_entry, render_agent_response
from core.entry_filter import filter_entry


class ProcessedNewsIds(Protocol):
    def seen(self, canonical_id: str) -> bool: ...

    def mark(self, canonical_id: str) -> None: ...


class InMemoryProcessedNewsIds:
    def __init__(self):
        self._ids = set()
        self._lock = threading.Lock()

    def seen(self, canonical_id: str) -> bool:
        with self._lock:
            return canonical_id in self._ids

    def mark(self, canonical_id: str) -> None:
        with self._lock:
            self._ids.add(canonical_id)


DEFAULT_PREPROCESS_PROMPT = """You are a helpful assistant.
Return a JSON object with fields:
summary, ai_category, subject, subject_type, region, event_type, group_hint, confidence.
Only return JSON with no extra text.
Input:
${content}
"""


def _normalize_url(url):
    if not url:
        return ""
    text = url.strip()
    if not text:
        return ""
    split = urlsplit(text)
    if split.scheme or split.netloc:
        scheme = split.scheme.lower()
        netloc = split.netloc.lower()
        path = split.path.rstrip("/")
        query = split.query
        if query:
            params = [
                (key, value)
                for key, value in parse_qsl(query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
            ]
            query = urlencode(params, doseq=True)
        return urlunsplit((scheme, netloc, path, query, ""))
    return text.rstrip("/")


def _normalize_title(title):
    if not title:
        return ""
    return re.sub(r"\s+", " ", title.strip())


def make_canonical_id(url, title):
    key_str = _normalize_url(url) + "\n" + _normalize_title(title)
    return hashlib.sha1(key_str.encode("utf-8")).hexdigest()


def _build_agent_prefixes(config):
    start_with_list = [name[1]["title"] for name in config.agents.items()]
    style_block = [name[1]["style_block"] for name in config.agents.items()]
    for enabled in style_block:
        if enabled:
            start_with_list.append("<blockquote>")
    return tuple(start_with_list)


def _should_preprocess_entry(config, entry):
    prefixes = _build_agent_prefixes(config)
    content = entry.get("content") or ""
    if prefixes and content.startswith(prefixes):
        return False
    return True


def _build_preprocess_input(entry):
    title = entry.get("title") or ""
    body = entry.get("content") or ""
    return f"Title: {title}\n\nBody:\n{body}"


def _parse_preprocess_output(raw):
    if not raw:
        return None
    text = raw.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def preprocess_entry(entry, config, llm_client, logger):
    if not _should_preprocess_entry(config, entry):
        return None
    prompt = getattr(config, "preprocess_prompt", None) or DEFAULT_PREPROCESS_PROMPT
    request = _build_preprocess_input(entry)
    try:
        raw = llm_client.get_result(prompt, request, logger)
    except Exception as e:
        if logger:
            logger.error(f"Error preprocessing entry {entry.get('id')}: {e}")
        return None
    parsed = _parse_preprocess_output(raw)
    if parsed is None and logger:
        logger.error(f"Error preprocessing entry {entry.get('id')}: invalid_json")
    return parsed


def process_entry(
    miniflux_client,
    entry,
    config,
    llm_client,
    logger,
    entries_repository=None,
    processed_entries_repository=None,
):
    dedup_marker = config.miniflux_dedup_marker
    entry_id = str(entry["id"])

    if logger and hasattr(logger, "debug"):
        logger.debug(f"process_entry: start entry_id={entry_id}")

    if dedup_marker and dedup_marker in (entry.get("content") or ""):
        logger.info(
            f"Skipping entry {entry_id} - already processed (dedup marker found)"
        )
        return

    if processed_entries_repository is not None:
        if processed_entries_repository.contains(entry_id):
            logger.info(
                f"Skipping entry {entry_id} - already processed (in processed records)"
            )
            return

    preprocess_result = preprocess_entry(entry, config, llm_client, logger)
    summary_text = None
    if preprocess_result:
        summary_text = preprocess_result.get("summary")
    canonical_id = make_canonical_id(entry.get("url"), entry.get("title"))

    if logger and hasattr(logger, "debug"):
        logger.debug(
            f"process_entry: processing entry_id={entry_id} agents={list(config.agents.keys())}"
        )

    llm_result = ""
    active_entries_repository = entries_repository or EntriesRepository(
        path="entries.json"
    )

    for agent in config.agents.items():
        if filter_entry(config, agent, entry):
            try:
                response_content = llm_client.get_result(
                    agent[1]["prompt"],
                    entry["content"],
                    logger,
                )
            except Exception as e:
                logger.error(
                    f"Error processing entry {entry['id']} with agent {agent[0]}: {e}"
                )
                continue
            log_content = (
                (response_content or "")[:20] + "..."
                if len(response_content or "") > 20
                else response_content
            )
            logger.info(f"agents:{agent[0]} feed_id:{entry['id']} result:{log_content}")

            if logger and hasattr(logger, "debug"):
                logger.debug(
                    f"process_entry: agent={agent[0]} entry_id={entry_id} response_length={len(response_content or '')}"
                )

            if agent[0] == "summary":
                entry_list = build_summary_entry(entry, summary_text or response_content)
                entry_list.update(
                    {
                        "id": canonical_id,
                        "ai_category": (preprocess_result or {}).get("ai_category"),
                        "ai_subject": (preprocess_result or {}).get("subject"),
                        "ai_subject_type": (preprocess_result or {}).get("subject_type"),
                        "ai_region": (preprocess_result or {}).get("region"),
                        "ai_event_type": (preprocess_result or {}).get("event_type"),
                        "ai_group_hint": (preprocess_result or {}).get("group_hint"),
                        "ai_confidence": (preprocess_result or {}).get("confidence"),
                    }
                )
                active_entries_repository.append_summary_item(entry_list)

            llm_result = llm_result + render_agent_response(agent[1], response_content)

    if len(llm_result) > 0:
        new_content = llm_result + entry["content"]
        if dedup_marker:
            new_content = new_content + "\n" + dedup_marker
        miniflux_client.update_entry(entry["id"], content=new_content)

        if logger and hasattr(logger, "debug"):
            logger.debug(
                f"process_entry: updated entry {entry_id} with dedup_marker={bool(dedup_marker)}"
            )

        if processed_entries_repository is not None:
            processed_entries_repository.add(entry_id)


def build_rate_limited_processor(
    config,
    entries_repository=None,
    processed_entries_repository=None,
    processed_news_ids=None,
):
    @sleep_and_retry
    @limits(calls=config.llm_RPM, period=60)
    def _processor(miniflux_client, entry, llm_client, logger):
        if processed_news_ids is not None:
            canonical_id = make_canonical_id(entry.get("url"), entry.get("title"))
            if processed_news_ids.seen(canonical_id):
                if logger and hasattr(logger, "debug"):
                    logger.debug(
                        f"process_entry: skip_duplicate canonical_id={canonical_id} url={entry.get('url')} title={entry.get('title')}"
                    )
                return
            processed_news_ids.mark(canonical_id)
        return process_entry(
            miniflux_client,
            entry,
            config,
            llm_client,
            logger,
            entries_repository=entries_repository,
            processed_entries_repository=processed_entries_repository,
        )

    return _processor
