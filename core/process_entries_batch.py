import concurrent.futures
import traceback


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
