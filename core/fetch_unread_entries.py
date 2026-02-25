import time

from core.process_entries_batch import process_entries_batch

def fetch_unread_entries(config, miniflux_client, entry_processor, llm_client, logger):
    entries = miniflux_client.get_entries(status=['unread'], limit=10000)
    start_time = time.time()
    logger.info('Get unread entries: ' + str(len(entries['entries']))) if len(entries['entries']) > 0 else logger.info('No new entries')

    if not entries['entries']:
        return

    process_entries_batch(
        config,
        entries['entries'],
        miniflux_client,
        entry_processor,
        llm_client,
        logger,
    )

    if len(entries['entries']) > 0 and time.time() - start_time >= 3:
        logger.info('Done')
