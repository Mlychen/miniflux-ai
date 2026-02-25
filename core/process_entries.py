from ratelimit import limits, sleep_and_retry

from common.entries_repository import EntriesRepository
from core.entry_rendering import build_summary_entry, render_agent_response
from core.entry_filter import filter_entry

def process_entry(
    miniflux_client,
    entry,
    config,
    llm_client,
    logger,
    entries_repository=None,
):
    #Todo change to queue
    llm_result = ''
    active_entries_repository = entries_repository or EntriesRepository(path='entries.json')

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
            log_content = (response_content or "")[:20] + '...' if len(response_content or "") > 20 else response_content
            logger.info(f"agents:{agent[0]} feed_id:{entry['id']} result:{log_content}")

            # save for ai_summary
            if agent[0] == 'summary':
                entry_list = build_summary_entry(entry, response_content)
                active_entries_repository.append_summary_item(entry_list)

            llm_result = llm_result + render_agent_response(agent[1], response_content)

    if len(llm_result) > 0:
        miniflux_client.update_entry(entry['id'], content= llm_result + entry['content'])


def build_rate_limited_processor(config, entries_repository=None):
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
        )

    return _processor
