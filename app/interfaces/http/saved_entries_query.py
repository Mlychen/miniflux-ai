from flask import current_app, jsonify, request

from app.interfaces.http.services import get_app_services


def _parse_limit(value_raw):
    if value_raw is None or str(value_raw).strip() == "":
        return 50, None
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


def register_saved_entries_query_routes(app):
    @app.route("/miniflux-ai/user/saved-entries", methods=["GET"])
    def list_saved_entries():
        services = get_app_services(current_app)
        logger = services.logger
        repository = services.saved_entries_repository
        if repository is None:
            return (
                jsonify({"status": "error", "message": "saved entries repository not configured"}),
                500,
            )

        title = str(request.args.get("title") or "").strip()

        mode = str(request.args.get("match") or "prefix").strip().lower()
        if mode not in {"prefix", "contains", "exact"}:
            return jsonify({"status": "error", "message": "invalid match"}), 400

        limit, limit_error = _parse_limit(request.args.get("limit"))
        if limit_error:
            return jsonify({"status": "error", "message": limit_error}), 400

        offset, offset_error = _parse_offset(request.args.get("offset"))
        if offset_error:
            return jsonify({"status": "error", "message": offset_error}), 400

        try:
            items = repository.search_by_title(
                title=title, mode=mode, limit=limit, offset=offset
            )
            total = repository.count_by_title(title=title, mode=mode)
        except Exception as e:
            if logger and hasattr(logger, "error"):
                logger.error(f"saved-entries-list: query failed error={e}")
            return jsonify({"status": "error", "message": "saved entries query failed"}), 500

        return jsonify(
            {
                "status": "ok",
                "title_filter": title,
                "match": mode,
                "limit": limit,
                "offset": offset,
                "count": len(items),
                "total": total,
                "entries": items,
            }
        )
