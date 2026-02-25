import json
import markdown
from ratelimit import limits, sleep_and_retry
import threading

from core.entry_filter import filter_entry
from core.get_ai_result import get_ai_result

file_lock = threading.Lock()

def process_entry(miniflux_client, entry, config, llm_client, logger, entries_file='entries.json', lock=None):
    #Todo change to queue
    llm_result = ''
    active_lock = lock or file_lock

    for agent in config.agents.items():
        # filter, if AI is not generating, and in allow_list, or not in deny_list
        if filter_entry(config, agent, entry):

            try:
                response_content = get_ai_result(llm_client, config, agent[1]["prompt"], entry["content"], logger)
            except Exception as e:
                logger.error(
                    f"Error processing entry {entry['id']} with agent {agent[0]}: {e}"
                )
                continue
            log_content = (response_content or "")[:20] + '...' if len(response_content or "") > 20 else response_content
            logger.info(f"agents:{agent[0]} feed_id:{entry['id']} result:{log_content}")

            # save for ai_summary
            if agent[0] == 'summary':
                entry_list = {
                    'datetime': entry['created_at'],
                    'category': entry['feed']['category']['title'],
                    'title': entry['title'],
                    'content': response_content,
                    'url': entry['url']
                }
                with active_lock:
                    try:
                        with open(entries_file, 'r', encoding='utf-8') as file:
                            data = json.load(file)
                    except (FileNotFoundError, json.JSONDecodeError):
                        data = []
                    data.append(entry_list)
                    with open(entries_file, 'w', encoding='utf-8') as file:
                        json.dump(data, file, indent=4, ensure_ascii=False)

            if agent[1]['style_block']:
                llm_result = (llm_result + '<blockquote>\n  <p><strong>'
                              + agent[1]['title'] + '</strong> '
                              + response_content.replace('\n', '').replace('\r', '')
                              + '\n</p>\n</blockquote><br/>')
            else:
                llm_result = llm_result + f"{agent[1]['title']}{markdown.markdown(response_content)}<hr><br />"

    if len(llm_result) > 0:
        miniflux_client.update_entry(entry['id'], content= llm_result + entry['content'])


def build_rate_limited_processor(config):
    @sleep_and_retry
    @limits(calls=config.llm_RPM, period=60)
    def _processor(miniflux_client, entry, llm_client, logger, entries_file='entries.json', lock=None):
        return process_entry(
            miniflux_client,
            entry,
            config,
            llm_client,
            logger,
            entries_file=entries_file,
            lock=lock,
        )

    return _processor
