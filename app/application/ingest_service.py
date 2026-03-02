import concurrent.futures
import time


def process_entries_batch(
    config,
    entries,
    miniflux_client,
    entry_processor,
    llm_client,
    logger,
):
    if not entries:
        return {'total': 0, 'failures': 0}

    if logger and hasattr(logger, 'debug'):
        logger.debug(
            f"process_entries_batch: total_entries={len(entries)} max_workers={config.llm_max_workers}"
        )

    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.llm_max_workers) as executor:
        futures = [
            executor.submit(
                entry_processor,
                miniflux_client,
                entry,
                llm_client,
                logger,
            )
            for entry in entries
        ]

        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                failures += 1
                if logger:
                    logger.error(f"process_entries_batch: generated an exception: {e}", exc_info=True)

    return {'total': len(entries), 'failures': failures}


def fetch_unread_entries(config, miniflux_client, entry_processor, llm_client, logger):
    entries = miniflux_client.get_entries(status=['unread'], limit=10000)
    start_time = time.time()
    if logger and hasattr(logger, 'debug'):
        logger.debug(
            f"fetch_unread_entries: fetched {len(entries.get('entries', []))} entries"
        )
    logger.info('Get unread entries: ' + str(len(entries['entries']))) if len(entries['entries']) > 0 else logger.info('No new entries')

    if not entries['entries']:
        return

    if logger and hasattr(logger, 'debug') and entries['entries']:
        sample_ids = [e.get('id') for e in entries['entries'][:3]]
        logger.debug(f"fetch_unread_entries: sample entry ids {sample_ids}")

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
