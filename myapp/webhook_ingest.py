from flask import request, abort, jsonify, current_app
import hmac
import hashlib

from core.process_entries_batch import process_entries_batch
from myapp.services import get_app_services


def register_webhook_routes(app):
    @app.route("/miniflux-ai/webhook/entries", methods=["POST"])
    def miniflux_ai():
        services = get_app_services(current_app)
        config = services.config
        logger = services.logger
        miniflux_client = services.miniflux_client
        llm_client = services.llm_client
        entry_processor = services.entry_processor
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

        # Check if webhook queue is configured
        webhook_queue = current_app.config.get("WEBHOOK_QUEUE")
        if webhook_queue:
            task = {
                "entries": batch_entries,
                "feed": feed,
            }
            success = webhook_queue.enqueue(task)
            if not success:
                logger.warning("Webhook queue is full, rejecting request")
                return jsonify({"status": "error", "message": "queue full"}), 503
            logger.info(
                f"Enqueued {len(batch_entries)} entries to webhook queue (size: {webhook_queue.size()})"
            )
            if logger and hasattr(logger, "debug"):
                logger.debug(
                    f"webhook: enqueue_success queue_size={webhook_queue.size()} task_entries={len(batch_entries)}"
                )
            return jsonify({"status": "accepted"}), 202

        # No queue - process synchronously (legacy behavior)
        result = process_entries_batch(
            config,
            batch_entries,
            miniflux_client,
            entry_processor,
            llm_client,
            logger,
        )
        if result["failures"] > 0:
            return jsonify({"status": "error"}), 500

        if logger and hasattr(logger, "debug"):
            logger.debug(
                f"webhook: sync_processing_done total={result['total']} failures={result['failures']}"
            )

        return jsonify({"status": "ok"})
