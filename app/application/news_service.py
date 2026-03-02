import time
from collections import defaultdict

from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.domain.ai_news_helpers import compose_daily_news_content, find_ai_news_feed_id


def safe_llm_call(prompt, text, logger, llm_client, retries=2, backoff_seconds=1.0):
    last_error = None
    for attempt in range(retries + 1):
        try:
            result = llm_client.get_result(prompt, text, logger)
            return result, None
        except Exception as e:
            last_error = e
            if logger:
                logger.error(
                    f"LLM call failed attempt={attempt + 1} retries={retries + 1} error={e}"
                )
            if attempt < retries and backoff_seconds:
                time.sleep(backoff_seconds * (attempt + 1))
    return None, last_error


def _fallback_greeting():
    hour = time.localtime().tm_hour
    if hour < 12:
        prefix = "早上好"
    elif hour < 18:
        prefix = "下午好"
    else:
        prefix = "晚上好"
    date_text = time.strftime("%Y-%m-%d")
    return f"{prefix}，今天是 {date_text}"


def _dedup_entries(entries):
    seen_ids = set()
    seen_keys = set()
    unique = []
    for entry in entries:
        entry_id = entry.get("id")
        if entry_id:
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            unique.append(entry)
            continue
        key = (entry.get("url"), entry.get("title"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(entry)
    return unique


def _derive_final_tags(entry):
    category = entry.get("category")
    ai_category = entry.get("ai_category")
    ai_subject = entry.get("ai_subject")
    ai_region = entry.get("ai_region")
    ai_event_type = entry.get("ai_event_type")

    final_category = category or ai_category or "其他"
    final_subject = ai_subject or ""
    final_region = ai_region or ""
    final_event_type = ai_event_type or ""

    return {
        "final_category": final_category,
        "final_subject": final_subject,
        "final_region": final_region,
        "final_event_type": final_event_type,
    }


def _choose_group_key(final_tags, entry):
    final_category = final_tags.get("final_category") or ""
    final_subject = final_tags.get("final_subject") or ""
    final_region = final_tags.get("final_region") or ""
    category = entry.get("category") or ""

    if final_category and final_subject:
        return f"{final_category} / {final_subject}"
    if final_category and final_region:
        return f"{final_category} / {final_region}"
    if final_category:
        return final_category
    if final_subject:
        return final_subject
    if final_region:
        return final_region
    if category:
        return category
    return "其他"


def _group_entries(entries):
    grouped = defaultdict(list)
    order = []
    for entry in entries:
        final_tags = _derive_final_tags(entry)
        group_key = _choose_group_key(final_tags, entry)
        if group_key not in grouped:
            order.append(group_key)
        grouped[group_key].append({**entry, **final_tags})

    for group_key, items in grouped.items():
        items.sort(
            key=lambda item: (
                item.get("datetime") or "",
                item.get("title") or "",
                item.get("id") or "",
            ),
            reverse=True,
        )

    return order, grouped


def _build_summary_block_input(group_order, grouped):
    blocks = []
    for group_key in group_order:
        blocks.append(f"【{group_key}】")
        for item in grouped.get(group_key, []):
            title = item.get("title") or ""
            summary = item.get("content") or ""
            blocks.append(f"- {title}")
            blocks.append(f"  {summary}")
        blocks.append("")
    return "\n".join(blocks).strip()


def _build_degraded_summary_block_input(group_order, grouped):
    blocks = []
    for group_key in group_order:
        blocks.append(f"【{group_key}】")
        for item in grouped.get(group_key, []):
            title = item.get("title") or ""
            summary = item.get("content") or ""
            datetime_text = item.get("datetime") or ""
            blocks.append(f"- {datetime_text} {title}".strip())
            if summary:
                blocks.append(f"  {summary}")
        blocks.append("")
    return "\n".join(blocks).strip()


def generate_daily_news(
    miniflux_client,
    config,
    llm_client,
    logger,
    ai_news_repository=None,
    entries_repository=None,
):
    logger.info('Generating daily news')
    sqlite_path = getattr(config, 'storage_sqlite_path', 'runtime/miniflux_ai.db')
    active_entries_repository = entries_repository or EntriesRepositorySQLite(path=sqlite_path)
    entries = active_entries_repository.read_all()
    active_ai_news_repository = ai_news_repository or AiNewsRepositorySQLite(path=sqlite_path)

    if not entries:
        logger.info('No entries to generate daily news')
        return []

    try:
        if logger and hasattr(logger, 'debug'):
            logger.debug(f'generate_daily_news: entries_count={len(entries)}')
        unique_entries = _dedup_entries(entries)
        group_order, grouped = _group_entries(unique_entries)
        contents = _build_summary_block_input(group_order, grouped)
        if logger and hasattr(logger, 'debug'):
            logger.debug(f'generate_daily_news: concatenated_content_length={len(contents)}')
        greeting, err_g = safe_llm_call(
            config.ai_news_prompts['greeting'],
            time.strftime('%B %d, %Y at %I:%M %p'),
            logger,
            llm_client,
        )
        if greeting is None:
            greeting = _fallback_greeting()
            if logger:
                logger.warning("generate_daily_news: greeting_degraded")
        if logger and hasattr(logger, 'debug'):
            logger.debug(f'generate_daily_news: greeting_length={len(greeting or "")}')
        summary_block, err_sb = safe_llm_call(
            config.ai_news_prompts['summary_block'],
            contents,
            logger,
            llm_client,
        )
        summary_block_degraded = False
        if summary_block is None:
            summary_block = _build_degraded_summary_block_input(group_order, grouped)
            summary_block_degraded = True
            if logger:
                logger.warning("generate_daily_news: summary_block_degraded")
        if logger and hasattr(logger, 'debug'):
            logger.debug(
                f'generate_daily_news: summary_block_length={len(summary_block or "")}'
            )
        summary = None
        if summary_block and not summary_block_degraded:
            summary, err_s = safe_llm_call(
                config.ai_news_prompts['summary'],
                summary_block,
                logger,
                llm_client,
            )
            if summary is None and logger:
                logger.warning("generate_daily_news: summary_degraded")
        if logger and hasattr(logger, 'debug'):
            logger.debug(f'generate_daily_news: summary_length={len(summary or "")}')

        if summary:
            response_content = compose_daily_news_content(
                greeting, summary, summary_block
            )
        else:
            response_content = f"{greeting}\n\n### News\n{summary_block}"
        logger.info('Generated daily news successfully')
        active_ai_news_repository.save_latest(response_content)
        if logger and hasattr(logger, 'debug'):
            logger.debug(
                f'generate_daily_news: saved_content_length={len(response_content or "")}'
            )

        feeds = miniflux_client.get_feeds()
        ai_news_feed_id = find_ai_news_feed_id(feeds)

        if ai_news_feed_id:
            miniflux_client.refresh_feed(ai_news_feed_id)
            logger.debug('Successfully refreshed the ai_news feed in Miniflux!')

    except Exception as e:
        logger.error(f'Error generating daily news: {e}')

    finally:
        try:
            active_entries_repository.clear_all()
            logger.info('Cleared entries repository')
        except Exception as e:
            logger.error(f'Failed to clear entries repository: {e}')
