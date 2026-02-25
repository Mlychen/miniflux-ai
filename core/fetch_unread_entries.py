import concurrent.futures
import time
import traceback

def fetch_unread_entries(config, miniflux_client, entry_processor, llm_client, logger, entries_file='entries.json', lock=None):
    entries = miniflux_client.get_entries(status=['unread'], limit=10000)
    start_time = time.time()
    logger.info('Get unread entries: ' + str(len(entries['entries']))) if len(entries['entries']) > 0 else logger.info('No new entries')

    if not entries['entries']:
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.llm_max_workers) as executor:
        futures = [
            executor.submit(entry_processor, miniflux_client, entry, llm_client, logger, entries_file, lock)
            for entry in entries['entries']
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error('generated an exception: %s' % e)

    if len(entries['entries']) > 0 and time.time() - start_time >= 3:
        logger.info('Done')
