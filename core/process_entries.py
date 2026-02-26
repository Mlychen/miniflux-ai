from ratelimit import limits, sleep_and_retry

from common.entries_repository import EntriesRepository
from common.processed_entries_repository import ProcessedEntriesRepository
from core.entry_rendering import build_summary_entry, render_agent_response
from core.entry_filter import filter_entry


def process_entry(
    miniflux_client,
    entry,
    config,
    llm_client,
    logger,
    entries_repository=None,
    processed_entries_repository=None,
):
    # Deduplication check - only if processed_entries_repository is provided
    dedup_marker = config.miniflux_dedup_marker
    entry_id = str(entry["id"])

    # Check 1: Content already has dedup marker (only if dedup_marker is configured)
    if dedup_marker and dedup_marker in (entry.get("content") or ""):
        logger.info(
            f"Skipping entry {entry_id} - already processed (dedup marker found)"
        )
        return

    # Check 2: Entry ID already in processed records (only if repo is provided)
    if processed_entries_repository is not None:
        if processed_entries_repository.contains(entry_id):
            logger.info(
                f"Skipping entry {entry_id} - already processed (in processed records)"
            )
            return

    # Process entry
    llm_result = ""
    active_entries_repository = entries_repository or EntriesRepository(
        path="entries.json"
    )

    for agent in config.agents.items():
        # filter, if AI is not generating, and in allow_list, or not in deny_list
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

            # save for ai_summary
            if agent[0] == "summary":
                entry_list = build_summary_entry(entry, response_content)
                active_entries_repository.append_summary_item(entry_list)

            llm_result = llm_result + render_agent_response(agent[1], response_content)

    if len(llm_result) > 0:
        # Add dedup marker to content
        new_content = llm_result + entry["content"]
        if dedup_marker:
            new_content = new_content + "\n" + dedup_marker
        miniflux_client.update_entry(entry["id"], content=new_content)

        # Record processed entry ID if repo is provided
        if processed_entries_repository is not None:
            processed_entries_repository.add(entry_id)


def build_rate_limited_processor(
    config, entries_repository=None, processed_entries_repository=None
):
    @sleep_and_retry
    @limits(calls=config.llm_RPM, period=60)
    def _processor(miniflux_client, entry, llm_client, logger):
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
