import threading
import os
from typing import cast

from flask import Flask, current_app, jsonify, request, redirect, send_from_directory

from adapters.protocols import LLMRequestPoolProtocol
from common.ai_news_repository import AiNewsRepository
from common.entries_repository import EntriesRepository
from common.ai_news_repository_sqlite import AiNewsRepositorySQLite
from common.entries_repository_sqlite import EntriesRepositorySQLite
from core.process_entries_batch import process_entries_batch
from myapp.services import AppServices, get_app_services


def create_app(
    config,
    miniflux_client,
    llm_client,
    logger,
    entry_processor,
    entries_repository=None,
    ai_news_repository=None,
    webhook_queue=None,
):
    storage_backend = getattr(config, "storage_backend", "json")
    sqlite_path = getattr(config, "storage_sqlite_path", "runtime/miniflux_ai.db")

    if entries_repository is None:
        entries_lock = threading.Lock()
        if storage_backend == "sqlite":
            app_entries_repository = EntriesRepositorySQLite(
                path=sqlite_path, lock=entries_lock
            )
        else:
            app_entries_repository = EntriesRepository(
                path="entries.json", lock=entries_lock
            )
    else:
        app_entries_repository = entries_repository

    if ai_news_repository is None:
        ai_news_lock = threading.Lock()
        if storage_backend == "sqlite":
            app_ai_news_repository = AiNewsRepositorySQLite(
                path=sqlite_path, lock=ai_news_lock
            )
        else:
            app_ai_news_repository = AiNewsRepository(
                path="ai_news.json", lock=ai_news_lock
            )
    else:
        app_ai_news_repository = ai_news_repository
    app = Flask(__name__)
    app.config["APP_SERVICES"] = AppServices(
        config=config,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        logger=logger,
        entry_processor=entry_processor,
        entries_repository=app_entries_repository,
        ai_news_repository=app_ai_news_repository,
    )

    if webhook_queue:
        app.config["WEBHOOK_QUEUE"] = webhook_queue

    from myapp.ai_news_publish import register_ai_news_publish_routes
    from myapp.webhook_ingest import register_webhook_routes

    register_ai_news_publish_routes(app)
    register_webhook_routes(app)

    if getattr(config, "debug_enabled", False):
        debug_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "debug-ui")
        )

        @app.route("/debug", methods=["GET"])
        def debug_redirect():
            return redirect("/debug/", code=302)

        @app.route("/debug/", methods=["GET"])
        def debug_index():
            return send_from_directory(debug_dir, "index.html")

        @app.route("/debug/<path:filename>", methods=["GET"])
        def debug_static(filename):
            return send_from_directory(debug_dir, filename)

    @app.route("/miniflux-ai/manual-process", methods=["POST"])
    def manual_process():
        services = get_app_services(current_app)
        config = services.config
        logger = services.logger
        miniflux_client = services.miniflux_client
        llm_client = services.llm_client
        entry_processor = services.entry_processor

        data = request.json or {}
        entry_id_raw = data.get("entry_id")
        if entry_id_raw is None:
            return jsonify({"status": "error", "message": "missing entry_id"}), 400

        entry_id_str = str(entry_id_raw).strip()
        if not entry_id_str.isdigit():
            return jsonify({"status": "error", "message": "invalid entry_id"}), 400
        entry_id = int(entry_id_str)

        entries = []
        try:
            response = miniflux_client.get_entries(entry_ids=[entry_id], limit=1)
            entries = (response or {}).get("entries") or []
        except TypeError:
            try:
                response = miniflux_client.get_entries(entry_ids=[entry_id])
                entries = (response or {}).get("entries") or []
            except Exception:
                entries = []
        except Exception:
            entries = []

        if not entries:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "entry not found",
                        "entry_id": entry_id_str,
                    }
                ),
                404,
            )

        result = process_entries_batch(
            config,
            [entries[0]],
            miniflux_client,
            entry_processor,
            llm_client,
            logger,
        )
        if result.get("failures"):
            if logger:
                logger.error(f"manual-process: failed entry_id={entry_id_str}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "processing failed",
                        "entry_id": entry_id_str,
                    }
                ),
                500,
            )
        if logger:
            logger.info(f"manual-process: ok entry_id={entry_id_str}")
        return jsonify({"status": "ok", "entry_id": entry_id_str})

    @app.route("/miniflux-ai/user/llm-pool/clear", methods=["POST"])
    def clear_llm_pool():
        services = get_app_services(current_app)
        logger = services.logger
        llm_client = services.llm_client

        if not hasattr(llm_client, "clear_all") and not hasattr(
            llm_client, "reset_entry"
        ):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "llm pool does not support clearing",
                    }
                ),
                400,
            )

        data = request.json or {}
        entry_key = data.get("entry_key")
        pool = cast(LLMRequestPoolProtocol, llm_client)

        if entry_key:
            if hasattr(llm_client, "reset_entry"):
                pool.reset_entry(entry_key)
            if logger:
                logger.info(f"llm-pool: reset_entry entry_key={entry_key}")
            return jsonify({"status": "ok", "mode": "reset", "entry_key": entry_key})

        if hasattr(llm_client, "clear_all"):
            pool.clear_all()
        if logger:
            logger.info("llm-pool: clear_all")
        return jsonify({"status": "ok", "mode": "clear_all"})

    @app.route("/miniflux-ai/user/llm-pool/metrics", methods=["GET"])
    def llm_pool_metrics():
        services = get_app_services(current_app)
        llm_client = services.llm_client
        if not hasattr(llm_client, "get_metrics"):
            return jsonify(
                {"status": "error", "message": "llm pool metrics unavailable"}
            ), 400
        pool = cast(LLMRequestPoolProtocol, llm_client)
        metrics = pool.get_metrics()
        return jsonify({"status": "ok", "metrics": metrics})

    @app.route("/miniflux-ai/user/llm-pool/failed-entries", methods=["GET"])
    def llm_pool_failed_entries():
        services = get_app_services(current_app)
        llm_client = services.llm_client
        entries_repository = services.entries_repository
        if not hasattr(llm_client, "get_failed_entries"):
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "llm pool failed-entries unavailable",
                    }
                ),
                400,
            )
        limit_raw = request.args.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 100
        except ValueError:
            limit = 100
        if limit <= 0:
            limit = 1
        pool = cast(LLMRequestPoolProtocol, llm_client)
        failed = pool.get_failed_entries(limit=limit)
        summaries = []
        try:
            summaries = entries_repository.read_all()
        except Exception:
            summaries = []
        summary_index = {}
        for item in summaries:
            cid = item.get("id")
            if cid and cid not in summary_index:
                summary_index[cid] = item
        items = []
        for entry_key, state in failed.items():
            canonical_id = None
            is_ai_news = False
            if entry_key.startswith("ai-news-"):
                is_ai_news = True
            else:
                if ":" in entry_key:
                    canonical_id = entry_key.split(":", 1)[0]
            summary = summary_index.get(canonical_id) if canonical_id else None
            base = {
                "entry_key": entry_key,
                **state,
            }
            base["is_ai_news"] = is_ai_news
            if canonical_id:
                base["canonical_id"] = canonical_id
            if summary:
                base["title"] = summary.get("title")
                base["url"] = summary.get("url")
            items.append(base)
        return jsonify({"status": "ok", "items": items})

    return app
