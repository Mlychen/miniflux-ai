from flask import request, abort, jsonify, current_app
import hmac
import hashlib
import concurrent.futures
import traceback


def register_ai_summary_routes(app):
    @app.route('/api/miniflux-ai', methods=['POST'])
    def miniflux_ai():
        services = current_app.config['APP_SERVICES']
        config = services['config']
        logger = services['logger']
        miniflux_client = services['miniflux_client']
        llm_client = services['llm_client']
        entry_processor = services['entry_processor']
        entries_file = services['entries_file']
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
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.llm_max_workers) as executor:
            futures = []
            for i in entries['entries']:
                i['feed'] = entries['feed']
                futures.append(executor.submit(entry_processor, miniflux_client, i, llm_client, logger, entries_file, None))
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error('generated an exception: %s' % e)
                    return jsonify({'status': 'error'}), 500

        return jsonify({'status': 'ok'})
