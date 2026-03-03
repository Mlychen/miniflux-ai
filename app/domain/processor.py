import hashlib
import inspect
import json
import re
import threading
import time
import uuid
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ratelimit import limits, sleep_and_retry

from app.domain.entry_rendering import build_summary_entry, render_agent_response
from app.domain.entry_filter import filter_entry
from app.observability.trace import get_process_logger

# Initialize process logger
trace_logger = get_process_logger()


class ProcessedNewsIds(Protocol):
    def try_mark(self, canonical_id: str) -> bool: ...


class InMemoryProcessedNewsIds:
    def __init__(self):
        self._ids = set()
        self._lock = threading.Lock()

    def try_mark(self, canonical_id: str) -> bool:
        with self._lock:
            if canonical_id in self._ids:
                return False
            self._ids.add(canonical_id)
            return True


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


def _call_llm_with_entry_options(
    llm_client,
    prompt,
    request,
    logger,
):
    """调用 LLM 客户端。"""
    get_result = getattr(llm_client, "get_result")
    return get_result(prompt, request, logger)


def _trace_log(trace_id, entry_id, stage, action, status="pending", duration_ms=None, data=None):
    """Helper to log trace events."""
    extra = {
        "trace_id": trace_id,
        "entry_id": entry_id,
        "stage": stage,
        "action": action,
        "status": status,
        "duration_ms": duration_ms,
        "data": data,
    }
    trace_logger.info(f"Trace: {stage}.{action}", extra=extra)


def preprocess_entry(
    entry,
    config,
    llm_client,
    logger,
    trace_id=None,
    entry_id=None,
    canonical_id=None,
):
    if not _should_preprocess_entry(config, entry):
        return None
    prompt = getattr(config, "preprocess_prompt", None) or DEFAULT_PREPROCESS_PROMPT
    request_content = _build_preprocess_input(entry)

    if trace_id and entry_id:
        _trace_log(trace_id, entry_id, "preprocess", "llm_call_start", data={
            "canonical_id": canonical_id,
            "prompt_template": prompt,
            "input_text": request_content
        })

    try:
        raw = _call_llm_with_entry_options(
            llm_client,
            prompt,
            request_content,
            logger,
        )
    except Exception as e:
        if logger:
            logger.error(f"Error preprocessing entry {entry.get('id')}: {e}")
        if trace_id and entry_id:
            _trace_log(trace_id, entry_id, "preprocess", "llm_call_error", status="error", data={"canonical_id": canonical_id, "error": str(e)})
        return None

    if trace_id and entry_id:
        _trace_log(trace_id, entry_id, "preprocess", "llm_call_complete", data={"canonical_id": canonical_id, "raw_response": raw})

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
    canonical_id = make_canonical_id(entry.get("url"), entry.get("title"))
    trace_id = entry.get("_trace_id") or uuid.uuid4().hex
    start_time = time.time()
    marked_processed = False

    def _mark_processed(reason):
        nonlocal marked_processed
        if processed_entries_repository is None:
            _trace_log(trace_id, entry_id, "dedup", "mark_processed_skipped", status="warning", data={"canonical_id": canonical_id, "reason": "repo_none"})
            return
        if marked_processed:
            return
        try:
            processed_entries_repository.add(canonical_id)
            marked_processed = True
            _trace_log(
                trace_id,
                entry_id,
                "dedup",
                "mark_processed",
                status="success",
                data={"canonical_id": canonical_id, "reason": reason},
            )
        except Exception as e:
            if logger:
                logger.error(f"Failed to mark processed entry {entry_id}: {e}")
            _trace_log(
                trace_id,
                entry_id,
                "dedup",
                "mark_processed",
                status="error",
                data={"canonical_id": canonical_id, "reason": reason, "error": str(e)},
            )

    _trace_log(trace_id, entry_id, "process", "start", status="processing", data={"canonical_id": canonical_id})
    _trace_log(
        trace_id,
        entry_id,
        "canonical_id",
        "generated",
        status="success",
        data={"canonical_id": canonical_id, "processed_repo_exists": processed_entries_repository is not None},
    )

    if logger and hasattr(logger, "debug"):
        logger.debug(f"process_entry: start entry_id={entry_id} processed_repo={processed_entries_repository is not None}")

    if dedup_marker and dedup_marker in (entry.get("content") or ""):
        logger.info(
            f"Skipping entry {entry_id} - already processed (dedup marker found)"
        )
        _trace_log(trace_id, entry_id, "dedup", "check", status="skipped", data={"canonical_id": canonical_id, "reason": "dedup_marker_found"})
        _trace_log(
            trace_id,
            entry_id,
            "process",
            "complete",
            status="skipped",
            duration_ms=int((time.time() - start_time) * 1000),
            data={
                "canonical_id": canonical_id,
                "agents_processed": 0,
                "agent_details": [],
                "reason": "dedup_marker_found",
            },
        )
        return

    if processed_entries_repository is not None:
        if processed_entries_repository.contains(canonical_id):
            logger.info(
                f"Skipping entry {entry_id} - already processed (in processed records)"
            )
            _trace_log(
                trace_id,
                entry_id,
                "dedup",
                "check",
                status="skipped",
                data={"reason": "processed_repository_found", "canonical_id": canonical_id},
            )
            _trace_log(
                trace_id,
                entry_id,
                "process",
                "complete",
                status="skipped",
                duration_ms=int((time.time() - start_time) * 1000),
                data={
                    "canonical_id": canonical_id,
                    "agents_processed": 0,
                    "agent_details": [],
                    "reason": "processed_repository_found",
                },
            )
            return

    agents_items = list(config.agents.items())
    if not agents_items:
        _trace_log(
            trace_id,
            entry_id,
            "agent_process",
            "skipped_all",
            status="skipped",
            data={"canonical_id": canonical_id, "reason": "no_agents_configured"},
        )
        _trace_log(
            trace_id,
            entry_id,
            "process",
            "complete",
            status="skipped",
            duration_ms=int((time.time() - start_time) * 1000),
            data={"canonical_id": canonical_id, "agents_processed": 0, "agent_details": []},
        )
        _mark_processed("no_agents_configured")
        return

    if not any(filter_entry(config, agent, entry) for agent in agents_items):
        _trace_log(
            trace_id,
            entry_id,
            "agent_process",
            "skipped_all",
            status="skipped",
            data={"canonical_id": canonical_id, "reason": "all_agents_filtered"},
        )
        _trace_log(
            trace_id,
            entry_id,
            "process",
            "complete",
            status="skipped",
            duration_ms=int((time.time() - start_time) * 1000),
            data={"canonical_id": canonical_id, "agents_processed": 0, "agent_details": []},
        )
        _mark_processed("all_agents_filtered")
        return

    preprocess_start = time.time()
    _trace_log(trace_id, entry_id, "preprocess", "start", data={"canonical_id": canonical_id})
    preprocess_result = preprocess_entry(
        entry,
        config,
        llm_client,
        logger,
        trace_id=trace_id,
        entry_id=entry_id,
        canonical_id=canonical_id,
    )
    preprocess_duration = int((time.time() - preprocess_start) * 1000)

    summary_text = None
    ai_category = None
    if preprocess_result:
        summary_text = preprocess_result.get("summary")
        ai_category = preprocess_result.get("ai_category")
        _trace_log(trace_id, entry_id, "preprocess", "complete", status="success", duration_ms=preprocess_duration, data={"canonical_id": canonical_id, **preprocess_result})
    else:
        _trace_log(trace_id, entry_id, "preprocess", "complete", status="warning", duration_ms=preprocess_duration, data={"canonical_id": canonical_id, "error": "no_result"})

    if logger and hasattr(logger, "debug"):
        logger.debug(
            f"process_entry: processing entry_id={entry_id} agents={list(config.agents.keys())}"
        )

    llm_result = ""
    if entries_repository is None:
        _trace_log(trace_id, entry_id, "process", "error", status="error", data={"canonical_id": canonical_id, "error": "entries_repository_missing"})
        raise RuntimeError("entries_repository must be provided")
    active_entries_repository = entries_repository

    matched_agents = 0
    agents_processed = 0
    agent_details = []
    agent_errors = []

    for agent in config.agents.items():
        agent_start = time.time()
        agent_name = agent[0]
        
        if filter_entry(config, agent, entry):
            matched_agents += 1
            _trace_log(trace_id, entry_id, "agent_process", "start", data={"canonical_id": canonical_id, "agent": agent_name})

            if agent_name == "summary":
                if summary_text:
                    response_content = summary_text
                    _trace_log(
                        trace_id,
                        entry_id,
                        "agent_process",
                        "llm_call_skipped",
                        status="success",
                        data={"canonical_id": canonical_id, "agent": agent_name, "reason": "use_preprocess_summary"},
                    )
                else:
                    agent_prompt = agent[1]["prompt"]
                    agent_input = entry["content"]
                    _trace_log(trace_id, entry_id, "agent_process", "llm_call_start", data={
                        "canonical_id": canonical_id,
                        "agent": agent_name,
                        "prompt_template": agent_prompt,
                        "input_text": agent_input,
                        "reason": "preprocess_summary_missing_fallback_to_agent_prompt",
                    })
                    try:
                        response_content = _call_llm_with_entry_options(
                            llm_client,
                            agent_prompt,
                            agent_input,
                            logger,
                        )
                    except Exception as e:
                        logger.error(
                            f"Error processing entry {entry['id']} with agent {agent_name}: {e}"
                        )
                        agent_errors.append({"agent": agent_name, "error": str(e)})
                        _trace_log(
                            trace_id,
                            entry_id,
                            "agent_process",
                            "error",
                            status="error",
                            duration_ms=int((time.time() - agent_start) * 1000),
                            data={"canonical_id": canonical_id, "agent": agent_name, "error": str(e)},
                        )
                        continue
            else:
                agent_prompt = agent[1]["prompt"]
                agent_input = entry["content"]
                _trace_log(trace_id, entry_id, "agent_process", "llm_call_start", data={
                    "canonical_id": canonical_id,
                    "agent": agent_name,
                    "prompt_template": agent_prompt,
                    "input_text": agent_input
                })

                try:
                    response_content = _call_llm_with_entry_options(
                        llm_client,
                        agent_prompt,
                        agent_input,
                        logger,
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing entry {entry['id']} with agent {agent_name}: {e}"
                    )
                    agent_errors.append({"agent": agent_name, "error": str(e)})
                    _trace_log(trace_id, entry_id, "agent_process", "error", status="error", duration_ms=int((time.time() - agent_start) * 1000), data={"canonical_id": canonical_id, "agent": agent_name, "error": str(e)})
                    continue

            if not (response_content or "").strip():
                agent_errors.append({"agent": agent_name, "error": "empty_response"})
                _trace_log(
                    trace_id,
                    entry_id,
                    "agent_process",
                    "error",
                    status="error",
                    duration_ms=int((time.time() - agent_start) * 1000),
                    data={"canonical_id": canonical_id, "agent": agent_name, "error": "empty_response"},
                )
                continue
             
            agent_duration = int((time.time() - agent_start) * 1000)
            log_content = (
                (response_content or "")[:20] + "..."
                if len(response_content or "") > 20
                else response_content
            )
            logger.info(f"agents:{agent_name} feed_id:{entry['id']} result:{log_content}")

            if logger and hasattr(logger, "debug"):
                logger.debug(
                    f"process_entry: agent={agent_name} entry_id={entry_id} response_length={len(response_content or '')}"
                )
            
            _trace_log(trace_id, entry_id, "agent_process", "complete", status="success", duration_ms=agent_duration, data={
                "canonical_id": canonical_id,
                "agent": agent_name,
                "response_length": len(response_content or ""),
                "raw_response": response_content
            })
            
            agents_processed += 1
            agent_details.append(agent_name)

            if agent_name == "summary":
                save_start = time.time()
                _trace_log(trace_id, entry_id, "save_result", "start", data={"canonical_id": canonical_id})
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
                _trace_log(trace_id, entry_id, "save_result", "complete", status="success", duration_ms=int((time.time() - save_start) * 1000), data={"canonical_id": canonical_id})

            llm_result = llm_result + render_agent_response(agent[1], response_content)
        else:
             _trace_log(trace_id, entry_id, "agent_process", "skipped", status="skipped", data={"canonical_id": canonical_id, "agent": agent_name, "reason": "filter_mismatch"})

    if matched_agents > 0 and agents_processed == 0:
        error_summary = {
            "canonical_id": canonical_id,
            "agents_processed": agents_processed,
            "agent_details": agent_details,
            "agent_errors": agent_errors,
            "reason": "all_matched_agents_failed",
        }
        _trace_log(
            trace_id,
            entry_id,
            "process",
            "complete",
            status="error",
            duration_ms=int((time.time() - start_time) * 1000),
            data=error_summary,
        )
        raise RuntimeError(
            f"process_entry failed: all matched agents failed entry_id={entry_id} canonical_id={canonical_id}"
        )

    if len(llm_result) <= 0:
        error_summary = {
            "canonical_id": canonical_id,
            "agents_processed": agents_processed,
            "agent_details": agent_details,
            "reason": "empty_rendered_result",
        }
        _trace_log(
            trace_id,
            entry_id,
            "process",
            "complete",
            status="error",
            duration_ms=int((time.time() - start_time) * 1000),
            data=error_summary,
        )
        raise RuntimeError(
            f"process_entry failed: empty rendered result entry_id={entry_id} canonical_id={canonical_id}"
        )

    update_start = time.time()
    _trace_log(trace_id, entry_id, "update_miniflux", "start", data={"canonical_id": canonical_id})
    new_content = llm_result + entry["content"]
    if dedup_marker:
        new_content = new_content + "\n" + dedup_marker
    try:
        miniflux_client.update_entry(entry["id"], content=new_content)
    except Exception as e:
        _trace_log(
            trace_id,
            entry_id,
            "update_miniflux",
            "error",
            status="error",
            duration_ms=int((time.time() - update_start) * 1000),
            data={"canonical_id": canonical_id, "error": str(e)},
        )
        raise
    _trace_log(
        trace_id,
        entry_id,
        "update_miniflux",
        "complete",
        status="success",
        duration_ms=int((time.time() - update_start) * 1000),
        data={
            "canonical_id": canonical_id,
            "content_length": len(new_content),
            "summary_length": len(summary_text or ""),
        },
    )

    if logger and hasattr(logger, "debug"):
        logger.debug(
            f"process_entry: updated entry {entry_id} with dedup_marker={bool(dedup_marker)}"
        )

    _mark_processed("updated_miniflux")

    _trace_log(trace_id, entry_id, "process", "complete", status="success", duration_ms=int((time.time() - start_time) * 1000), data={"canonical_id": canonical_id, "agents_processed": agents_processed, "agent_details": agent_details, "ai_category": ai_category})


def build_rate_limited_processor(
    config,
    entries_repository=None,
    processed_entries_repository=None,
    processed_news_ids=None,
):
    @sleep_and_retry
    @limits(calls=config.llm_RPM, period=60)
    def _processor(miniflux_client, entry, llm_client, logger):
        start_time = time.time()
        if processed_news_ids is not None:
            canonical_id = make_canonical_id(entry.get("url"), entry.get("title"))
            if not processed_news_ids.try_mark(canonical_id):
                trace_id = entry.get("_trace_id") or uuid.uuid4().hex
                entry_id = str(entry.get("id") or "")
                _trace_log(
                    trace_id,
                    entry_id,
                    "dedup",
                    "cache_hit",
                    status="warning",
                    data={
                        "reason": "in_memory_duplicate_cache_hit",
                        "canonical_id": canonical_id,
                        "enforced_by": "processed_news_ids",
                    },
                )
                if logger and hasattr(logger, "debug"):
                    logger.debug(
                        f"process_entry: cache_hit canonical_id={canonical_id} url={entry.get('url')} title={entry.get('title')}"
                    )
                _trace_log(
                    trace_id,
                    entry_id,
                    "process",
                    "complete",
                    status="skipped",
                    duration_ms=int((time.time() - start_time) * 1000),
                    data={
                        "canonical_id": canonical_id,
                        "agents_processed": 0,
                        "agent_details": [],
                        "reason": "in_memory_duplicate_cache_hit",
                    },
                )
                return None
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
