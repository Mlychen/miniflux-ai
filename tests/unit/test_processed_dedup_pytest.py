from core.process_entries import InMemoryProcessedNewsIds


def test_in_memory_processed_ids_dedup():
    dedup = InMemoryProcessedNewsIds()
    first = dedup.try_mark("id-1")
    second = dedup.try_mark("id-1")
    third = dedup.try_mark("id-2")
    assert first is True
    assert second is False
    assert third is True
