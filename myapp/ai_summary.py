from flask import request, abort, jsonify, current_app
import hmac
import hashlib

from core.process_entries_batch import process_entries_batch
from myapp.services import get_app_services


def register_ai_summary_routes(app):
    @app.route('/api/miniflux-ai', methods=['POST'])
    def miniflux_ai():
        services = get_app_services(current_app)
        config = services.config
        logger = services.logger
        miniflux_client = services.miniflux_client
        llm_client = services.llm_client
        entry_processor = services.entry_processor
        webhook_secret = config.miniflux_webhook_secret

        payload = request.get_data()
        signature = request.headers.get('X-Miniflux-Signature')
        if not webhook_secret:
            abort(403)
        if not signature:
            abort(403)
        hmac_signature = hmac.new(webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(hmac_signature, signature):
            abort(403)  # 返回403 Forbidden
        entries = request.json
        logger.info('Get unread entries via webhook: ' + str(len(entries['entries'])))

        batch_entries = []
        for i in entries['entries']:
            i['feed'] = entries['feed']
            batch_entries.append(i)

        result = process_entries_batch(
            config,
            batch_entries,
            miniflux_client,
            entry_processor,
            llm_client,
            logger,
        )
        if result['failures'] > 0:
            return jsonify({'status': 'error'}), 500

        return jsonify({'status': 'ok'})
