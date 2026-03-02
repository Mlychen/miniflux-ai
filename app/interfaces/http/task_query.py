from flask import current_app, jsonify, request

from app.domain.task_error_key import normalize_error_key
from app.domain.task_store import TASK_DEAD, TASK_RETRYABLE, TASK_STATUSES
from app.interfaces.http.services import get_app_services


def _serialize_task(task, include_payload=True):
    item = {
        "id": task.id,
        "canonical_id": task.canonical_id,
        "trace_id": task.trace_id,
        "status": task.status,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "next_retry_at": task.next_retry_at,
        "leased_until": task.leased_until,
        "last_error": task.last_error,
        "error_key": task.error_key,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }
    if include_payload:
        item["payload"] = task.payload
    return item


def _parse_limit(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return 100, None
    try:
        value = int(str(value_raw).strip())
    except (TypeError, ValueError):
        return None, "invalid limit"
    if value <= 0:
        return None, "invalid limit"
    return min(value, 500), None


def _parse_offset(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return 0, None
    try:
        value = int(str(value_raw).strip())
    except (TypeError, ValueError):
        return None, "invalid offset"
    if value < 0:
        return None, "invalid offset"
    return value, None


def _parse_include_payload(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return False, None

    normalized = str(value_raw).strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True, None
    if normalized in {"0", "false", "no"}:
        return False, None
    return None, "invalid include_payload"


def _parse_window_seconds(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return 300, None
    try:
        value = int(str(value_raw).strip())
    except (TypeError, ValueError):
        return None, "invalid window_seconds"
    if value < 60 or value > 3600:
        return None, "invalid window_seconds"
    return value, None


def _parse_failure_status(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return None, None
    status = str(value_raw).strip()
    if status not in {TASK_RETRYABLE, TASK_DEAD}:
        return None, "invalid failure status"
    return status, None


def _parse_requeue_status(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return TASK_DEAD, None
    status = str(value_raw).strip()
    if status not in {TASK_RETRYABLE, TASK_DEAD, "running"}:
        return None, "invalid requeue status"
    return status, None


def _parse_error_key_filter(error_key_raw, error_raw):
    if error_key_raw is not None and str(error_key_raw).strip() != "":
        return str(error_key_raw).strip(), None
    if error_raw is not None and str(error_raw).strip() != "":
        return normalize_error_key(str(error_raw)), None
    return None, None


def register_task_query_routes(app):
    @app.route("/miniflux-ai/user/tasks", methods=["GET"])
    def list_tasks():
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        status = request.args.get("status")
        if status is not None:
            status = str(status).strip()
        if status == "":
            status = None
        if status and status not in TASK_STATUSES:
            return jsonify({"status": "error", "message": "invalid status"}), 400

        limit, limit_error = _parse_limit(request.args.get("limit"))
        if limit_error:
            return jsonify({"status": "error", "message": limit_error}), 400

        offset, offset_error = _parse_offset(request.args.get("offset"))
        if offset_error:
            return jsonify({"status": "error", "message": offset_error}), 400

        include_payload, include_payload_error = _parse_include_payload(
            request.args.get("include_payload")
        )
        if include_payload_error:
            return jsonify({"status": "error", "message": include_payload_error}), 400

        try:
            tasks = task_store.list_tasks(
                status=status,
                limit=limit,
                offset=offset,
                include_payload=include_payload,
            )
            total = task_store.count_tasks(status=status)
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-list: query failed error={e}")
            return jsonify({"status": "error", "message": "task query failed"}), 500

        return jsonify(
            {
                "status": "ok",
                "status_filter": status,
                "limit": limit,
                "offset": offset,
                "count": len(tasks),
                "total": total,
                "include_payload": include_payload,
                "tasks": [
                    _serialize_task(item, include_payload=include_payload) for item in tasks
                ],
            }
        )

    @app.route("/miniflux-ai/user/tasks/metrics", methods=["GET"])
    def task_metrics():
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        window_seconds, window_error = _parse_window_seconds(
            request.args.get("window_seconds")
        )
        if window_error:
            return jsonify({"status": "error", "message": window_error}), 400

        try:
            metrics = task_store.get_metrics(throughput_window_seconds=window_seconds)
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-metrics: query failed error={e}")
            return jsonify({"status": "error", "message": "task query failed"}), 500

        counts = metrics.get("counts", {})
        return jsonify(
            {
                "status": "ok",
                "total": int(counts.get("total", 0)),
                "backlog": int(counts.get("backlog", 0)),
                **metrics,
            }
        )

    @app.route("/miniflux-ai/user/tasks/<task_id>", methods=["GET"])
    def get_task(task_id):
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        task_id_str = str(task_id).strip()
        if not task_id_str.isdigit():
            return jsonify({"status": "error", "message": "invalid task_id"}), 400
        task_id_int = int(task_id_str)

        try:
            task = task_store.get_task(task_id_int)
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-get: query failed task_id={task_id_str} error={e}")
            return jsonify({"status": "error", "message": "task query failed"}), 500

        if task is None:
            return jsonify({"status": "not_found", "task_id": task_id_str}), 404

        return jsonify({"status": "ok", "task": _serialize_task(task, include_payload=True)})

    @app.route("/miniflux-ai/user/tasks/failure-groups", methods=["GET"])
    def list_failure_groups():
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        status_filter, status_error = _parse_failure_status(request.args.get("status"))
        if status_error:
            return jsonify({"status": "error", "message": status_error}), 400

        limit, limit_error = _parse_limit(request.args.get("limit"))
        if limit_error:
            return jsonify({"status": "error", "message": limit_error}), 400

        offset, offset_error = _parse_offset(request.args.get("offset"))
        if offset_error:
            return jsonify({"status": "error", "message": offset_error}), 400

        error_key_filter, error_key_error = _parse_error_key_filter(
            request.args.get("error_key"),
            request.args.get("error"),
        )
        if error_key_error:
            return jsonify({"status": "error", "message": error_key_error}), 400

        try:
            groups = task_store.list_failure_groups(
                status=status_filter,
                error_key=error_key_filter,
                limit=limit,
                offset=offset,
            )
            total = task_store.count_failure_groups(
                status=status_filter,
                error_key=error_key_filter,
            )
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-failure-groups: query failed error={e}")
            return jsonify({"status": "error", "message": "task query failed"}), 500

        return jsonify(
            {
                "status": "ok",
                "status_filter": status_filter,
                "error_key_filter": error_key_filter,
                "limit": limit,
                "offset": offset,
                "count": len(groups),
                "total": total,
                "groups": groups,
            }
        )

    @app.route("/miniflux-ai/user/tasks/failure-groups/tasks", methods=["GET"])
    def list_failure_group_tasks():
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        status_filter, status_error = _parse_failure_status(request.args.get("status"))
        if status_error:
            return jsonify({"status": "error", "message": status_error}), 400

        error_key_filter, error_key_error = _parse_error_key_filter(
            request.args.get("error_key"),
            request.args.get("error"),
        )
        if error_key_error:
            return jsonify({"status": "error", "message": error_key_error}), 400

        limit, limit_error = _parse_limit(request.args.get("limit"))
        if limit_error:
            return jsonify({"status": "error", "message": limit_error}), 400

        offset, offset_error = _parse_offset(request.args.get("offset"))
        if offset_error:
            return jsonify({"status": "error", "message": offset_error}), 400

        include_payload, include_payload_error = _parse_include_payload(
            request.args.get("include_payload")
        )
        if include_payload_error:
            return jsonify({"status": "error", "message": include_payload_error}), 400

        try:
            tasks = task_store.list_failed_tasks(
                status=status_filter,
                error_key=error_key_filter,
                limit=limit,
                offset=offset,
                include_payload=include_payload,
            )
            total = task_store.count_failed_tasks(
                status=status_filter,
                error_key=error_key_filter,
            )
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-failure-group-tasks: query failed error={e}")
            return jsonify({"status": "error", "message": "task query failed"}), 500

        return jsonify(
            {
                "status": "ok",
                "status_filter": status_filter,
                "error_key_filter": error_key_filter,
                "limit": limit,
                "offset": offset,
                "count": len(tasks),
                "total": total,
                "include_payload": include_payload,
                "tasks": [
                    _serialize_task(item, include_payload=include_payload) for item in tasks
                ],
            }
        )

    @app.route("/miniflux-ai/user/tasks/failure-groups/requeue", methods=["POST"])
    def requeue_failure_groups():
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        payload = request.json if isinstance(request.json, dict) else {}
        status_filter, status_error = _parse_failure_status(payload.get("status"))
        if status_error:
            return jsonify({"status": "error", "message": status_error}), 400

        limit, limit_error = _parse_limit(payload.get("limit"))
        if limit_error:
            return jsonify({"status": "error", "message": limit_error}), 400

        error_key_filter, error_key_error = _parse_error_key_filter(
            payload.get("error_key"),
            payload.get("error"),
        )
        if error_key_error:
            return jsonify({"status": "error", "message": error_key_error}), 400

        try:
            requeued = task_store.requeue_tasks(
                status=status_filter,
                limit=limit,
                error_key=error_key_filter,
            )
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-failure-group-requeue: update failed error={e}")
            return jsonify({"status": "error", "message": "task update failed"}), 500

        return jsonify(
            {
                "status": "ok",
                "requeued": int(requeued),
                "status_filter": status_filter,
                "error_key_filter": error_key_filter,
                "limit": limit,
            }
        )

    @app.route("/miniflux-ai/user/tasks/<task_id>/requeue", methods=["POST"])
    def requeue_task(task_id):
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        task_id_str = str(task_id).strip()
        if not task_id_str.isdigit():
            return jsonify({"status": "error", "message": "invalid task_id"}), 400

        try:
            requeued = task_store.requeue_task(int(task_id_str))
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-requeue: update failed task_id={task_id_str} error={e}")
            return jsonify({"status": "error", "message": "task update failed"}), 500

        if not requeued:
            return jsonify({"status": "not_found", "task_id": task_id_str}), 404
        return jsonify({"status": "ok", "task_id": task_id_str, "requeued": True})

    @app.route("/miniflux-ai/user/tasks/requeue", methods=["POST"])
    def requeue_tasks():
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store
        if task_store is None:
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        payload = request.json if isinstance(request.json, dict) else {}
        status_filter, status_error = _parse_requeue_status(payload.get("status"))
        if status_error:
            return jsonify({"status": "error", "message": status_error}), 400

        limit, limit_error = _parse_limit(payload.get("limit"))
        if limit_error:
            return jsonify({"status": "error", "message": limit_error}), 400

        error_key_filter, error_key_error = _parse_error_key_filter(
            payload.get("error_key"),
            payload.get("error"),
        )
        if error_key_error:
            return jsonify({"status": "error", "message": error_key_error}), 400

        try:
            requeued = task_store.requeue_tasks(
                status=status_filter,
                limit=limit,
                error_key=error_key_filter,
            )
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"task-requeue-batch: update failed error={e}")
            return jsonify({"status": "error", "message": "task update failed"}), 500

        return jsonify(
            {
                "status": "ok",
                "requeued": int(requeued),
                "status_filter": status_filter,
                "error_key_filter": error_key_filter,
                "limit": limit,
            }
        )
