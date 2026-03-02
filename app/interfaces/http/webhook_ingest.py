from flask import request, abort, jsonify, current_app
import hmac
import hashlib
import uuid

from app.domain.processor import make_canonical_id
from app.interfaces.http.services import get_app_services


def register_webhook_routes(app):
    @app.route("/miniflux-ai/webhook/entries", methods=["POST"])
    def miniflux_ai():
        services = get_app_services(current_app)
        config = services.config
        logger = services.logger
        webhook_secret = config.miniflux_webhook_secret

        payload = request.get_data()
        signature = request.headers.get("X-Miniflux-Signature")
        if logger and hasattr(logger, "debug"):
            logger.debug(
                f"webhook: payload_length={len(payload)} has_signature={bool(signature)}"
            )
        if not webhook_secret:
            abort(403)
        if not signature:
            abort(403)
        hmac_signature = hmac.new(
            webhook_secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(hmac_signature, signature):
            abort(403)

        data = request.json or {}
        event_type = data.get("event_type")
        incoming_trace_id = request.headers.get("X-Trace-Id")
        payload_trace_id = data.get("trace_id")
        trace_id = ""
        if incoming_trace_id is not None:
            trace_id = str(incoming_trace_id).strip()
        if not trace_id and payload_trace_id is not None:
            trace_id = str(payload_trace_id).strip()
        if not trace_id:
            trace_id = uuid.uuid4().hex

        if event_type == "save_entry":
            if logger:
                logger.info("Received save_entry webhook event, ignoring for now")
            return jsonify({"status": "ignored", "reason": "save_entry not processed"}), 200

        entries = data.get("entries")
        feed = data.get("feed")

        if not isinstance(entries, list) or not feed:
            if logger:
                logger.error("Invalid webhook payload: missing entries or feed")
            return jsonify({"status": "error", "message": "invalid payload"}), 400

        logger.info("Get unread entries via webhook: " + str(len(entries)))

        batch_entries = []
        for i in entries:
            i["feed"] = feed
            batch_entries.append(i)

        if logger and hasattr(logger, "debug"):
            logger.debug(
                f"webhook: batch_entries_count={len(batch_entries)} feed_site={feed.get('site_url')}"
            )

        task_store = current_app.config.get("TASK_STORE")
        if task_store is None:
            if logger:
                logger.error("Webhook task store is not configured")
            return jsonify({"status": "error", "message": "task store not configured"}), 500

        accepted = 0
        duplicates = 0
        max_attempts = int(getattr(config, "miniflux_task_max_attempts", 5))
        for entry in batch_entries:
            canonical_id = make_canonical_id(entry.get("url"), entry.get("title"))
            payload = {"entry": entry, "feed": feed}
            try:
                created = task_store.create_task(
                    canonical_id=canonical_id,
                    payload=payload,
                    trace_id=trace_id,
                    max_attempts=max_attempts,
                )
            except Exception as e:
                if logger:
                    logger.error(f"Webhook task persistence failed: {e}")
                return (
                    jsonify({"status": "error", "message": "task persistence failed"}),
                    500,
                )
            if created:
                accepted += 1
            else:
                duplicates += 1

        if logger:
            logger.info(
                f"Webhook tasks persisted accepted={accepted} duplicates={duplicates} trace_id={trace_id}"
            )
        return (
            jsonify(
                {
                    "status": "accepted",
                    "accepted": accepted,
                    "duplicates": duplicates,
                    "trace_id": trace_id,
                }
            ),
            202,
        )
