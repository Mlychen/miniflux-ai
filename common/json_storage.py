import json
import threading


_DEFAULT_FILE_LOCK = threading.Lock()


def _active_lock(lock):
    return lock or _DEFAULT_FILE_LOCK


def read_json_file(path, default_factory, lock=None):
    with _active_lock(lock):
        try:
            with open(path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return default_factory()


def write_json_file(path, data, lock=None):
    with _active_lock(lock):
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)


def append_json_list_item(path, item, lock=None):
    with _active_lock(lock):
        try:
            with open(path, 'r', encoding='utf-8') as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            data = []

        if not isinstance(data, list):
            data = []

        data.append(item)

        with open(path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)


def consume_json_file(path, empty_value, default_factory, lock=None):
    with _active_lock(lock):
        try:
            with open(path, 'r', encoding='utf-8') as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            data = default_factory()

        with open(path, 'w', encoding='utf-8') as file:
            json.dump(empty_value, file, indent=4, ensure_ascii=False)

    return data
