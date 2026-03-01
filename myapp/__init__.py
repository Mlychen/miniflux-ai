import threading
import os
import uuid
from typing import cast

import miniflux
from flask import Flask, current_app, jsonify, request, redirect, send_from_directory

from adapters.protocols import LLMRequestPoolProtocol
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
    task_store=None,
):
    sqlite_path = getattr(config, "storage_sqlite_path", "runtime/miniflux_ai.db")

    if entries_repository is None:
        entries_lock = threading.Lock()
        app_entries_repository = EntriesRepositorySQLite(
            path=sqlite_path, lock=entries_lock
        )
    else:
        app_entries_repository = entries_repository

    if ai_news_repository is None:
        ai_news_lock = threading.Lock()
        app_ai_news_repository = AiNewsRepositorySQLite(
            path=sqlite_path, lock=ai_news_lock
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
        task_store=task_store,
    )

    if task_store:
        app.config["TASK_STORE"] = task_store

    from myapp.ai_news_publish import register_ai_news_publish_routes
    from myapp.task_query import register_task_query_routes
    from myapp.webhook_ingest import register_webhook_routes

    register_ai_news_publish_routes(app)
    register_webhook_routes(app)
    register_task_query_routes(app)

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

        @app.route("/miniflux-ai/user/miniflux/me", methods=["GET"])
        def debug_miniflux_me():
            services = get_app_services(current_app)
            miniflux_client = services.miniflux_client
            logger = services.logger
            try:
                me = miniflux_client.me()
                return jsonify({"status": "ok", "me": me})
            except miniflux.ClientError as e:
                if logger:
                    logger.error(
                        f"debug-miniflux-me: miniflux error status_code={e.status_code} reason={e.get_error_reason()}"
                    )
                return jsonify({"status": "error", "message": "miniflux error"}), 502
            except Exception as e:
                if logger:
                    logger.error(f"debug-miniflux-me: unexpected error error={e}")
                return jsonify({"status": "error", "message": "unexpected error"}), 500

        @app.route("/miniflux-ai/user/miniflux/entry/<int:entry_id>", methods=["GET"])
        def debug_miniflux_entry(entry_id: int):
            services = get_app_services(current_app)
            miniflux_client = services.miniflux_client
            logger = services.logger
            try:
                entry = (
                    miniflux_client.get_entry(entry_id)
                    if hasattr(miniflux_client, "get_entry")
                    else None
                )
                if not entry:
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": "entry not found",
                                "entry_id": str(entry_id),
                            }
                        ),
                        404,
                    )
                slim = {
                    "id": entry.get("id"),
                    "status": entry.get("status"),
                    "title": entry.get("title"),
                    "url": entry.get("url"),
                    "feed_id": entry.get("feed_id"),
                    "published_at": entry.get("published_at"),
                    "created_at": entry.get("created_at"),
                }
                return jsonify({"status": "ok", "entry": slim})
            except miniflux.ResourceNotFound:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "entry not found",
                            "entry_id": str(entry_id),
                        }
                    ),
                    404,
                )
            except miniflux.ClientError as e:
                if logger:
                    logger.error(
                        f"debug-miniflux-entry: miniflux error entry_id={entry_id} status_code={e.status_code} reason={e.get_error_reason()}"
                    )
                return jsonify({"status": "error", "message": "miniflux error"}), 502
            except Exception as e:
                if logger:
                    logger.error(
                        f"debug-miniflux-entry: unexpected error entry_id={entry_id} error={e}"
                    )
                return jsonify({"status": "error", "message": "unexpected error"}), 500

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
        trace_id_raw = data.get("trace_id")
        trace_id = str(trace_id_raw).strip() if trace_id_raw is not None else ""
        if not trace_id:
            trace_id = uuid.uuid4().hex

        if logger:
            logger.info(
                f"manual-process: request entry_id={entry_id_str} trace_id={trace_id} remote={request.remote_addr}"
            )

        try:
            if hasattr(miniflux_client, "get_entry"):
                entry = miniflux_client.get_entry(entry_id)
                entries = [entry] if entry else []
            else:
                response = miniflux_client.get_entries(entry_ids=[entry_id], limit=1)
                entries = (response or {}).get("entries") or []

            if not entries:
                if logger:
                    logger.error(
                        f"manual-process: entry not found entry_id={entry_id_str} remote={request.remote_addr}"
                    )
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
        except miniflux.ResourceNotFound:
            if logger:
                logger.error(
                    f"manual-process: entry not found entry_id={entry_id_str} remote={request.remote_addr}"
                )
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
        except miniflux.AccessUnauthorized as e:
            if logger:
                logger.error(
                    f"manual-process: miniflux unauthorized entry_id={entry_id_str} reason={e.get_error_reason()}"
                )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "miniflux unauthorized",
                        "entry_id": entry_id_str,
                    }
                ),
                502,
            )
        except miniflux.AccessForbidden as e:
            if logger:
                logger.error(
                    f"manual-process: miniflux forbidden entry_id={entry_id_str} reason={e.get_error_reason()}"
                )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "miniflux forbidden",
                        "entry_id": entry_id_str,
                    }
                ),
                502,
            )
        except miniflux.BadRequest as e:
            if logger:
                logger.error(
                    f"manual-process: miniflux bad request entry_id={entry_id_str} reason={e.get_error_reason()}"
                )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "miniflux bad request",
                        "entry_id": entry_id_str,
                    }
                ),
                502,
            )
        except miniflux.ClientError as e:
            if logger:
                logger.error(
                    f"manual-process: miniflux error entry_id={entry_id_str} status_code={e.status_code} reason={e.get_error_reason()}"
                )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "miniflux error",
                        "entry_id": entry_id_str,
                    }
                ),
                502,
            )
        except Exception as e:
            if logger:
                logger.error(f"manual-process: unexpected error entry_id={entry_id_str} error={e}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "unexpected error",
                        "entry_id": entry_id_str,
                    }
                ),
                500,
            )

        trace_entry = dict(entries[0])
        trace_entry["_trace_id"] = trace_id

        result = process_entries_batch(
            config,
            [trace_entry],
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
                        "trace_id": trace_id,
                    }
                ),
                500,
            )
        if logger:
            logger.info(f"manual-process: ok entry_id={entry_id_str}")
        return jsonify({"status": "ok", "entry_id": entry_id_str, "trace_id": trace_id})

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

    @app.route("/miniflux-ai/user/processed-entries", methods=["GET"])
    def processed_entries():
        services = get_app_services(current_app)
        entries_repository = services.entries_repository
        
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        
        try:
            limit = int(limit_raw) if limit_raw is not None else 100
        except ValueError:
            limit = 100
        if limit <= 0: limit = 100
            
        try:
            offset = int(offset_raw) if offset_raw is not None else 0
        except ValueError:
            offset = 0
        if offset < 0: offset = 0
            
        try:
            all_entries = entries_repository.read_all()
            # Sort by datetime desc
            all_entries.sort(key=lambda x: x.get("datetime") or "", reverse=True)

            # Backfill trace_id / entry_id from process logs using canonical_id.
            # Historical summaries may only have `id` (canonical_id), so we enrich at read time.
            trace_index = {}
            log_path = os.path.join("logs", "manual-process.log")
            if os.path.exists(log_path):
                import json

                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (
                            record.get("stage") != "process"
                            or record.get("action") != "complete"
                        ):
                            continue
                        data = record.get("data") or {}
                        canonical_id = data.get("canonical_id")
                        if not canonical_id:
                            continue
                        timestamp = record.get("timestamp") or ""
                        prev = trace_index.get(canonical_id)
                        if prev and prev.get("timestamp", "") > timestamp:
                            continue
                        trace_index[canonical_id] = {
                            "entry_id": str(record.get("entry_id") or ""),
                            "trace_id": str(record.get("trace_id") or ""),
                            "timestamp": timestamp,
                        }

            total = len(all_entries)
            page_entries = all_entries[offset : offset + limit]
            normalized_entries = []
            for item in page_entries:
                row = dict(item)
                canonical_id = str(row.get("canonical_id") or row.get("id") or "")
                trace_info = trace_index.get(canonical_id, {})
                entry_id = str(
                    row.get("entry_id")
                    or row.get("source_entry_id")
                    or trace_info.get("entry_id")
                    or ""
                )
                trace_id = str(row.get("trace_id") or trace_info.get("trace_id") or "")
                row["canonical_id"] = canonical_id
                # Keep API contract: `id` is what UI shows as Entry ID.
                row["id"] = entry_id
                row["entry_id"] = entry_id
                row["trace_id"] = trace_id
                normalized_entries.append(row)

            return jsonify({
                "status": "ok",
                "total": total,
                "limit": limit,
                "offset": offset,
                "entries": normalized_entries
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/miniflux-ai/user/process-trace/<entry_id>", methods=["GET"])
    def get_process_trace(entry_id):
        from common.logger import get_process_logger
        import json
        
        # This implementation reads from the log file. 
        # In a production system with high volume, this should be indexed in a DB.
        # For our scale, scanning the log file is acceptable.
        
        target_id = str(entry_id).strip()
        # Simple heuristic: trace_id is usually 32 hex chars. entry_id is usually digits.
        is_trace_id = len(target_id) > 20 and not target_id.isdigit()

        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
            return jsonify({"status": "not_found", "message": "Log file not found"}), 404
            
        # If querying by Entry ID, we first find all associated Trace IDs
        if not is_trace_id:
            found_traces = {} # trace_id -> summary
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            if str(record.get("entry_id")) == target_id:
                                trace_id = record.get("trace_id")
                                if not trace_id: continue
                                
                                if trace_id not in found_traces:
                                    found_traces[trace_id] = {
                                        "trace_id": trace_id,
                                        "entry_id": target_id,
                                        "start_time": record.get("timestamp"),
                                        "status": "pending",
                                        "stages_count": 0
                                    }
                                
                                t = found_traces[trace_id]
                                t["stages_count"] += 1
                                
                                if record.get("stage") == "process" and record.get("action") == "complete":
                                    t["status"] = record.get("status")
                                    t["total_duration_ms"] = record.get("duration_ms")
                                    if record.get("data"):
                                        t.update(record.get("data"))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                 return jsonify({"status": "error", "message": str(e)}), 500

            trace_list = list(found_traces.values())
            # Sort by start_time desc
            trace_list.sort(key=lambda x: x.get("start_time") or "", reverse=True)
            
            if not trace_list:
                return jsonify({"status": "not_found", "id": target_id}), 404
                
            return jsonify({
                "status": "ok",
                "type": "list",
                "id": target_id,
                "traces": trace_list
            })

        # If querying by Trace ID, return detailed stages
        stages = []
        summary = None
        
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        
                        if str(record.get("trace_id")) == target_id:
                            # Convert to UI format
                            stage_data = {
                                "timestamp": record.get("timestamp"),
                                "stage": record.get("stage"),
                                "action": record.get("action"),
                                "status": record.get("status"),
                                "duration_ms": record.get("duration_ms"),
                                "data": record.get("data")
                            }
                            stages.append(stage_data)
                            
                            # Check for completion to build summary
                            if record.get("stage") == "process" and record.get("action") == "complete":
                                summary = {
                                    "entry_id": str(record.get("entry_id")),
                                    "trace_id": record.get("trace_id"),
                                    "status": record.get("status"),
                                    "total_duration_ms": record.get("duration_ms"),
                                    "end_time": record.get("timestamp"),
                                    # Extract data from the complete record
                                    ** (record.get("data") or {})
                                }
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
            
        if not stages:
            return jsonify({"status": "not_found", "id": target_id}), 404
            
        # Fill in start time if we have summary
        if summary and stages:
            summary["start_time"] = stages[0]["timestamp"]
            summary["stages_count"] = len(stages)
            
        # If no summary found (process incomplete or mixed logs), try to build partial summary
        if not summary and stages:
            last = stages[-1]
            summary = {
                "entry_id": str(stages[0]["data"].get("entry_id")) if stages[0].get("data") else "",
                "status": "pending" if last["status"] != "error" else "error",
                "start_time": stages[0]["timestamp"],
                "stages_count": len(stages)
            }

        return jsonify({
            "status": "ok", 
            "type": "detail",
            "entry_id": summary.get("entry_id"), 
            "trace_id": target_id,
            "summary": summary,
            "stages": stages
        })

    @app.route("/miniflux-ai/user/process-history", methods=["GET"])
    def get_process_history():
        limit_raw = request.args.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 20
        except ValueError:
            limit = 20
            
        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
             return jsonify({"status": "ok", "total": 0, "traces": []})
             
        import json
        traces = {} # Map trace_id -> trace_summary
        
        # Read file in reverse would be better for performance, but for now standard read
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                # We need to process all lines to aggregate by trace_id
                # Optimization: In a real scenario, we might want to rotate logs or use a DB
                for line in f:
                    try:
                        record = json.loads(line)
                        trace_id = record.get("trace_id")
                        if not trace_id: continue
                        
                        if trace_id not in traces:
                            traces[trace_id] = {
                                "trace_id": trace_id,
                                "entry_id": str(record.get("entry_id")),
                                "start_time": record.get("timestamp"),
                                "status": "pending",
                                "stages_count": 0
                            }
                        
                        t = traces[trace_id]
                        t["stages_count"] += 1
                        
                        # Update if this is a completion record
                        if record.get("stage") == "process" and record.get("action") == "complete":
                            t["status"] = record.get("status")
                            t["total_duration_ms"] = record.get("duration_ms")
                            if record.get("data"):
                                t.update(record.get("data"))
                                
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
            
        # Convert to list and sort by start_time desc
        trace_list = list(traces.values())
        trace_list.sort(key=lambda x: x.get("start_time") or "", reverse=True)
        
        total = len(trace_list)
        result_traces = trace_list[:limit]
        
        return jsonify({
            "status": "ok",
            "total": total,
            "limit": limit,
            "traces": result_traces
        })

    return app
