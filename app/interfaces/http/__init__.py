import threading
import os
import uuid

import miniflux
from flask import Flask, current_app, jsonify, request, redirect, send_from_directory

from app.infrastructure.miniflux_gateway import MinifluxGatewayError
from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
from app.infrastructure.saved_entries_repository_sqlite import SavedEntriesRepositorySQLite
from app.infrastructure.summary_archive_repository_sqlite import SummaryArchiveRepositorySQLite
from app.application.ingest_service import process_entries_batch
from app.interfaces.http.services import AppServices, get_app_services


def create_app(
    config,
    miniflux_client,
    llm_client,
    logger,
    entry_processor,
    entries_repository=None,
    ai_news_repository=None,
    saved_entries_repository=None,
    summary_archive_repository=None,
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

    if saved_entries_repository is None:
        saved_entries_lock = threading.Lock()
        app_saved_entries_repository = SavedEntriesRepositorySQLite(
            path=sqlite_path, lock=saved_entries_lock
        )
    else:
        app_saved_entries_repository = saved_entries_repository

    if summary_archive_repository is None:
        summary_archive_lock = threading.Lock()
        app_summary_archive_repository = SummaryArchiveRepositorySQLite(
            path=sqlite_path, lock=summary_archive_lock
        )
    else:
        app_summary_archive_repository = summary_archive_repository

    app = Flask(__name__)
    app.config["APP_SERVICES"] = AppServices(
        config=config,
        miniflux_client=miniflux_client,
        llm_client=llm_client,
        logger=logger,
        entry_processor=entry_processor,
        entries_repository=app_entries_repository,
        ai_news_repository=app_ai_news_repository,
        saved_entries_repository=app_saved_entries_repository,
        summary_archive_repository=app_summary_archive_repository,
        task_store=task_store,
    )

    if task_store:
        app.config["TASK_STORE"] = task_store

    from app.interfaces.http.ai_news_publish import register_ai_news_publish_routes
    from app.interfaces.http.saved_entries_query import register_saved_entries_query_routes
    from app.interfaces.http.task_query import register_task_query_routes
    from app.interfaces.http.webhook_ingest import register_webhook_routes

    register_ai_news_publish_routes(app)
    register_webhook_routes(app)
    register_task_query_routes(app)
    register_saved_entries_query_routes(app)

    if getattr(config, "debug_enabled", False):
        debug_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "debug-ui")
        )

        # 模块化 Debug UI（Vite 构建产物）
        debug_dist_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "debug-ui", "dist")
        )

        @app.route("/debug", methods=["GET"])
        def debug_redirect():
            return redirect("/debug/", code=302)

        @app.route("/debug/", methods=["GET"])
        def debug_index():
            # 如果 dist 目录存在则使用构建产物，否则使用开发版本
            if os.path.exists(os.path.join(debug_dist_dir, "index.html")):
                return send_from_directory(debug_dist_dir, "index.html")
            else:
                return send_from_directory(debug_dir, "index-v2.html")

        @app.route("/debug/<path:filename>", methods=["GET"])
        def debug_static(filename):
            if os.path.exists(os.path.join(debug_dist_dir, "index.html")):
                return send_from_directory(debug_dist_dir, filename)
            else:
                return send_from_directory(debug_dir, filename)

        @app.route("/miniflux-ai/user/miniflux/me", methods=["GET"])
        def debug_miniflux_me():
            services = get_app_services(current_app)
            miniflux_client = services.miniflux_client
            logger = services.logger
            try:
                me = miniflux_client.me()
                return jsonify({"status": "ok", "me": me})
            except MinifluxGatewayError as e:
                if logger:
                    logger.error(
                        f"debug-miniflux-me: miniflux error status_code={e.status_code} reason={e.reason}"
                    )
                return jsonify({"status": "error", "message": "miniflux error"}), 502
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
            except MinifluxGatewayError as e:
                if e.status_code == 404:
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
                if logger:
                    logger.error(
                        f"debug-miniflux-entry: miniflux error entry_id={entry_id} status_code={e.status_code} reason={e.reason}"
                    )
                return jsonify({"status": "error", "message": "miniflux error"}), 502
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
        except MinifluxGatewayError as e:
            if e.status_code == 404:
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
            if logger:
                logger.error(
                    f"manual-process: miniflux error entry_id={entry_id_str} status_code={e.status_code} reason={e.reason}"
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
        """重试失败任务，通过 TaskStore 重新入队。"""
        services = get_app_services(current_app)
        logger = services.logger
        task_store = services.task_store

        if task_store is None:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "task store unavailable",
                    }
                ),
                400,
            )

        data = request.json or {}
        task_id = data.get("task_id")

        if task_id:
            # 重试单个任务
            try:
                success = task_store.requeue_task(int(task_id))
                if success:
                    if logger:
                        logger.info(f"task-store: requeue_task task_id={task_id}")
                    return jsonify({"status": "ok", "mode": "requeue", "task_id": task_id})
                else:
                    return jsonify(
                        {"status": "error", "message": f"task {task_id} not requeueable"}
                    ), 400
            except Exception as e:
                return jsonify(
                    {"status": "error", "message": str(e)}
                ), 500

        # 批量重试 dead 任务
        try:
            count = task_store.requeue_tasks(status="dead", limit=100)
            if logger:
                logger.info(f"task-store: requeue_tasks count={count}")
            return jsonify({"status": "ok", "mode": "requeue_batch", "count": count})
        except Exception as e:
            return jsonify(
                {"status": "error", "message": str(e)}
            ), 500

    @app.route("/miniflux-ai/user/llm-pool/metrics", methods=["GET"])
    def llm_pool_metrics():
        services = get_app_services(current_app)
        llm_client = services.llm_client
        if not hasattr(llm_client, "get_metrics"):
            return jsonify(
                {"status": "error", "message": "llm pool metrics unavailable"}
            ), 400
        metrics = llm_client.get_metrics()
        return jsonify({"status": "ok", "metrics": metrics})

    @app.route("/miniflux-ai/user/llm-pool/failed-entries", methods=["GET"])
    def llm_pool_failed_entries():
        """从 TaskStore 获取失败任务（retryable/dead 状态）。"""
        services = get_app_services(current_app)
        task_store = services.task_store
        entries_repository = services.entries_repository

        if task_store is None:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "task store unavailable",
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

        # 从 TaskStore 获取失败任务
        failed_tasks = task_store.list_failed_tasks(limit=limit)
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
        for task in failed_tasks:
            canonical_id = task.canonical_id
            is_ai_news = canonical_id.startswith("ai-news-") if canonical_id else False
            summary = summary_index.get(canonical_id) if canonical_id else None

            base = {
                "task_id": task.id,
                "canonical_id": canonical_id,
                "status": task.status,
                "attempts": task.attempts,
                "max_attempts": task.max_attempts,
                "last_error": task.last_error,
                "error_key": task.error_key,
                "next_retry_at": task.next_retry_at,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "is_ai_news": is_ai_news,
            }
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
        if limit <= 0:
            limit = 100
            
        try:
            offset = int(offset_raw) if offset_raw is not None else 0
        except ValueError:
            offset = 0
        if offset < 0:
            offset = 0
            
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
                                if not trace_id:
                                    continue

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

        # === If querying by Trace ID, return batch with all canonical_ids ===
        # Collect: 1) batch summary 2) all entries (by canonical_id) with their stages
        entries_by_canonical = {}  # canonical_id -> {stages: [], entry_id, status, ...}
        batch_start_time = None
        batch_end_time = None

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)

                        if str(record.get("trace_id")) == target_id:
                            data = record.get("data") or {}
                            canonical_id = data.get("canonical_id")
                            record_entry_id = str(record.get("entry_id") or "")

                            # 对于没有 canonical_id 的记录，使用 entry_id 作为临时标识
                            entry_key = canonical_id or f"entry-{record_entry_id}"

                            # 初始化条目
                            if entry_key not in entries_by_canonical:
                                entries_by_canonical[entry_key] = {
                                    "canonical_id": canonical_id,
                                    "entry_id": record_entry_id,
                                    "stages": [],
                                    "status": "pending",
                                    "ai_category": None,
                                    "start_time": record.get("timestamp"),
                                    "end_time": None,
                                    "duration_ms": None,
                                }

                            entry = entries_by_canonical[entry_key]

                            # 添加阶段
                            stage_data = {
                                "timestamp": record.get("timestamp"),
                                "stage": record.get("stage"),
                                "action": record.get("action"),
                                "status": record.get("status"),
                                "duration_ms": record.get("duration_ms"),
                                "data": data
                            }
                            entry["stages"].append(stage_data)

                            # 更新时间范围
                            ts = record.get("timestamp")
                            if ts:
                                if entry["start_time"] > ts:
                                    entry["start_time"] = ts
                                if entry["end_time"] is None or entry["end_time"] < ts:
                                    entry["end_time"] = ts

                                if batch_start_time is None or batch_start_time > ts:
                                    batch_start_time = ts
                                if batch_end_time is None or batch_end_time < ts:
                                    batch_end_time = ts

                            # 更新条目状态
                            if record.get("stage") == "process" and record.get("action") == "complete":
                                record_status = record.get("status") or "success"
                                # 兼容 "ok" 状态，统一为 "success"
                                if record_status in ("ok", "success"):
                                    record_status = "success"
                                entry["status"] = record_status
                                entry["duration_ms"] = record.get("duration_ms")
                                if data.get("ai_category"):
                                    entry["ai_category"] = data.get("ai_category")
                            elif record.get("status") == "error":
                                entry["status"] = "error"

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        if not entries_by_canonical:
            return jsonify({"status": "not_found", "id": target_id}), 404

        # 构建批次汇总
        entries_list = list(entries_by_canonical.values())
        total_entries = len(entries_list)
        success_count = sum(1 for e in entries_list if e["status"] == "success")
        error_count = sum(1 for e in entries_list if e["status"] == "error")

        # 批次状态
        if total_entries == 0:
            batch_status = "pending"
        elif success_count == total_entries:
            batch_status = "success"
        elif error_count == total_entries:
            batch_status = "error"
        else:
            batch_status = "partial"

        # 计算总耗时
        total_duration_ms = None
        if batch_start_time and batch_end_time:
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(batch_start_time.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(batch_end_time.replace("Z", "+00:00"))
                total_duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
            except Exception:
                pass

        # 构建条目摘要列表
        entries_summary = []
        for entry in entries_list:
            entries_summary.append({
                "canonical_id": entry["canonical_id"],
                "entry_id": entry["entry_id"],
                "status": entry["status"],
                "ai_category": entry["ai_category"],
                "stages_count": len(entry["stages"]),
                "duration_ms": entry["duration_ms"],
            })

        return jsonify({
            "status": "ok",
            "type": "batch",
            "trace_id": target_id,
            "summary": {
                "status": batch_status,
                "total_entries": total_entries,
                "success_count": success_count,
                "error_count": error_count,
                "start_time": batch_start_time,
                "total_duration_ms": total_duration_ms,
            },
            "entries": entries_summary,
        })

    @app.route("/miniflux-ai/user/process-history", methods=["GET"])
    def get_process_history():
        """
        获取处理历史列表，按 trace_id（批次）聚合。

        返回格式：
        {
          "traces": [
            {
              "trace_id": "xxx",
              "start_time": "...",
              "status": "success",  // 批次整体状态：success/partial/error
              "total_entries": 3,
              "success_count": 2,
              "error_count": 1,
              "duration_ms": 5000
            }
          ]
        }
        """
        limit_raw = request.args.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 20
        except ValueError:
            limit = 20

        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
             return jsonify({"status": "ok", "total": 0, "traces": []})

        import json

        # 第一层：trace_id -> 批次信息
        # 第二层：trace_id -> canonical_id -> 条目状态
        batches = {}  # trace_id -> batch_info
        batch_entries = {}  # trace_id -> {canonical_id -> entry_info}

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        trace_id = record.get("trace_id")
                        if not trace_id:
                            continue

                        # 初始化批次
                        if trace_id not in batches:
                            batches[trace_id] = {
                                "trace_id": trace_id,
                                "start_time": record.get("timestamp"),
                                "end_time": None,
                            }
                            batch_entries[trace_id] = {}

                        # 更新批次时间
                        if record.get("timestamp"):
                            batch_ts = record.get("timestamp")
                            if batches[trace_id]["start_time"] > batch_ts:
                                batches[trace_id]["start_time"] = batch_ts
                            if batches[trace_id]["end_time"] is None or batches[trace_id]["end_time"] < batch_ts:
                                batches[trace_id]["end_time"] = batch_ts

                        # 提取 canonical_id
                        data = record.get("data") or {}
                        canonical_id = data.get("canonical_id")
                        entry_id = str(record.get("entry_id") or "")

                        # 对于没有 canonical_id 的记录，使用 entry_id 作为临时标识
                        entry_key = canonical_id or f"entry-{entry_id}"

                        # 初始化条目
                        if entry_key not in batch_entries[trace_id]:
                            batch_entries[trace_id][entry_key] = {
                                "canonical_id": canonical_id,
                                "entry_id": entry_id,
                                "status": "pending",
                                "ai_category": None,
                                "start_time": record.get("timestamp"),
                                "end_time": None,
                            }

                        entry_info = batch_entries[trace_id][entry_key]

                        # 更新条目时间
                        if record.get("timestamp"):
                            if entry_info["start_time"] > record.get("timestamp"):
                                entry_info["start_time"] = record.get("timestamp")
                            if entry_info["end_time"] is None or entry_info["end_time"] < record.get("timestamp"):
                                entry_info["end_time"] = record.get("timestamp")

                        # 更新条目状态
                        if record.get("stage") == "process" and record.get("action") == "complete":
                            record_status = record.get("status") or "success"
                            # 兼容 "ok" 状态，统一为 "success"
                            if record_status in ("ok", "success"):
                                record_status = "success"
                            entry_info["status"] = record_status
                            entry_info["duration_ms"] = record.get("duration_ms")
                            if data.get("ai_category"):
                                entry_info["ai_category"] = data.get("ai_category")
                        elif record.get("status") == "error":
                            entry_info["status"] = "error"

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        # 构建批次汇总
        trace_list = []
        for trace_id, batch_info in batches.items():
            entries = batch_entries.get(trace_id, {})
            total_entries = len(entries)
            success_count = sum(1 for e in entries.values() if e["status"] == "success")
            error_count = sum(1 for e in entries.values() if e["status"] == "error")

            # 计算批次状态
            if total_entries == 0:
                batch_status = "pending"
            elif success_count == total_entries:
                batch_status = "success"
            elif error_count == total_entries:
                batch_status = "error"
            else:
                batch_status = "partial"

            # 计算批次总耗时
            start_ts = batch_info["start_time"]
            end_ts = batch_info["end_time"]
            duration_ms = None
            if start_ts and end_ts:
                try:
                    from datetime import datetime
                    start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                    duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                except Exception:
                    pass

            trace_list.append({
                "trace_id": trace_id,
                "start_time": batch_info["start_time"],
                "status": batch_status,
                "total_entries": total_entries,
                "success_count": success_count,
                "error_count": error_count,
                "duration_ms": duration_ms,
            })

        # 按开始时间降序排序
        trace_list.sort(key=lambda x: x.get("start_time") or "", reverse=True)

        total = len(trace_list)
        result_traces = trace_list[:limit]

        return jsonify({
            "status": "ok",
            "total": total,
            "limit": limit,
            "traces": result_traces
        })

    @app.route("/miniflux-ai/user/process-search", methods=["GET"])
    def search_process_history():
        """
        根据 entry_id 或 canonical_id 搜索处理历史。

        参数：
        - q: 搜索关键词（entry_id 或 canonical_id）
        - limit: 返回数量限制

        返回格式：
        {
          "status": "ok",
          "query": "12345",
          "query_type": "entry_id",  // 或 "canonical_id"
          "total": 3,
          "traces": [
            {
              "trace_id": "xxx",
              "start_time": "...",
              "status": "success",
              "total_entries": 3,
              "success_count": 2,
              "error_count": 1,
              "duration_ms": 5000,
              "matched_entry": {
                "canonical_id": "cid-xxx",
                "entry_id": "12345",
                "status": "success",
                "ai_category": "AI新闻"
              }
            }
          ]
        }
        """
        import json
        from datetime import datetime

        query = request.args.get("q", "").strip()
        limit_raw = request.args.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 50
        except ValueError:
            limit = 50

        if not query:
            return jsonify({"status": "error", "message": "缺少搜索参数 q"}), 400

        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
            return jsonify({"status": "ok", "query": query, "query_type": None, "total": 0, "traces": []})

        # 判断查询类型：纯数字为 entry_id，否则为 canonical_id
        query_type = "entry_id" if query.isdigit() else "canonical_id"

        # 收集匹配的 trace_id 和对应条目信息
        matched_traces = {}  # trace_id -> {trace_info, matched_entry}

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        trace_id = record.get("trace_id")
                        if not trace_id:
                            continue

                        data = record.get("data") or {}
                        canonical_id = data.get("canonical_id", "")
                        entry_id = str(record.get("entry_id") or "")

                        # 匹配检查
                        is_match = False
                        if query_type == "entry_id" and entry_id == query:
                            is_match = True
                        elif query_type == "canonical_id" and canonical_id == query:
                            is_match = True

                        if not is_match:
                            continue

                        # 初始化批次信息
                        if trace_id not in matched_traces:
                            matched_traces[trace_id] = {
                                "trace_info": {
                                    "trace_id": trace_id,
                                    "start_time": record.get("timestamp"),
                                    "end_time": None,
                                },
                                "entries": {},  # canonical_id 或 entry_id key -> entry_info
                            }

                        # 更新批次时间
                        batch_ts = record.get("timestamp")
                        if batch_ts:
                            if matched_traces[trace_id]["trace_info"]["start_time"] > batch_ts:
                                matched_traces[trace_id]["trace_info"]["start_time"] = batch_ts
                            if matched_traces[trace_id]["trace_info"]["end_time"] is None or \
                               matched_traces[trace_id]["trace_info"]["end_time"] < batch_ts:
                                matched_traces[trace_id]["trace_info"]["end_time"] = batch_ts

                        # 使用 canonical_id 或 entry_id 作为条目标识
                        entry_key = canonical_id or f"entry-{entry_id}"

                        if entry_key not in matched_traces[trace_id]["entries"]:
                            matched_traces[trace_id]["entries"][entry_key] = {
                                "canonical_id": canonical_id,
                                "entry_id": entry_id,
                                "status": "pending",
                                "ai_category": None,
                            }

                        entry_info = matched_traces[trace_id]["entries"][entry_key]

                        # 更新条目状态
                        if record.get("stage") == "process" and record.get("action") == "complete":
                            record_status = record.get("status") or "success"
                            if record_status in ("ok", "success"):
                                record_status = "success"
                            entry_info["status"] = record_status
                            if data.get("ai_category"):
                                entry_info["ai_category"] = data.get("ai_category")
                        elif record.get("status") == "error":
                            entry_info["status"] = "error"

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        # 构建结果
        trace_list = []
        for trace_id, info in matched_traces.items():
            trace_info = info["trace_info"]
            entries = info["entries"]

            total_entries = len(entries)
            success_count = sum(1 for e in entries.values() if e["status"] == "success")
            error_count = sum(1 for e in entries.values() if e["status"] == "error")

            # 计算批次状态
            if total_entries == 0:
                batch_status = "pending"
            elif success_count == total_entries:
                batch_status = "success"
            elif error_count == total_entries:
                batch_status = "error"
            else:
                batch_status = "partial"

            # 计算持续时间
            start_ts = trace_info["start_time"]
            end_ts = trace_info["end_time"]
            duration_ms = None
            if start_ts and end_ts:
                try:
                    start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                    duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                except Exception:
                    pass

            # 找到匹配的条目
            matched_entry = None
            for entry_key, entry_info in entries.items():
                if query_type == "entry_id" and entry_info["entry_id"] == query:
                    matched_entry = entry_info
                    break
                elif query_type == "canonical_id" and entry_info["canonical_id"] == query:
                    matched_entry = entry_info
                    break

            trace_list.append({
                "trace_id": trace_id,
                "start_time": trace_info["start_time"],
                "status": batch_status,
                "total_entries": total_entries,
                "success_count": success_count,
                "error_count": error_count,
                "duration_ms": duration_ms,
                "matched_entry": matched_entry,
            })

        # 按开始时间降序排序
        trace_list.sort(key=lambda x: x.get("start_time") or "", reverse=True)

        total = len(trace_list)
        result_traces = trace_list[:limit]

        return jsonify({
            "status": "ok",
            "query": query,
            "query_type": query_type,
            "total": total,
            "limit": limit,
            "traces": result_traces
        })

    @app.route("/miniflux-ai/user/canonical-trace/<path:canonical_id>", methods=["GET"])
    def get_canonical_trace(canonical_id):
        """
        查询单个 canonical_id 在某个批次中的详细处理阶段。

        参数：
        - canonical_id: 条目逻辑唯一标识
        - trace_id (query): 批次 ID，用于限定查询范围

        返回该 canonical_id 在该批次中的所有 stages。
        """
        import json

        target_canonical_id = str(canonical_id).strip()
        trace_id_filter = request.args.get("trace_id", "").strip()

        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
            return jsonify({"status": "not_found", "message": "Log file not found"}), 404

        stages = []
        summary = None

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        data = record.get("data") or {}
                        record_canonical_id = data.get("canonical_id")
                        record_trace_id = str(record.get("trace_id") or "")

                        # 匹配条件：canonical_id 相同，且如果有 trace_id 过滤则也需匹配
                        if record_canonical_id == target_canonical_id:
                            # 如果指定了 trace_id 过滤，则只返回该批次的数据
                            if trace_id_filter and record_trace_id != trace_id_filter:
                                continue

                            stage_data = {
                                "timestamp": record.get("timestamp"),
                                "stage": record.get("stage"),
                                "action": record.get("action"),
                                "status": record.get("status"),
                                "duration_ms": record.get("duration_ms"),
                                "data": data
                            }
                            stages.append(stage_data)

                            # 提取完整记录用于构建摘要
                            if record.get("stage") == "process" and record.get("action") == "complete":
                                record_status = record.get("status") or "success"
                                # 兼容 "ok" 状态，统一为 "success"
                                if record_status in ("ok", "success"):
                                    record_status = "success"
                                summary = {
                                    "entry_id": str(record.get("entry_id")),
                                    "trace_id": record_trace_id,
                                    "canonical_id": target_canonical_id,
                                    "status": record_status,
                                    "total_duration_ms": record.get("duration_ms"),
                                    "end_time": record.get("timestamp"),
                                    "ai_category": data.get("ai_category"),
                                }

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        if not stages:
            return jsonify({
                "status": "not_found",
                "canonical_id": target_canonical_id,
                "trace_id": trace_id_filter or None
            }), 404

        # 构建摘要
        if summary:
            summary["start_time"] = stages[0]["timestamp"]
            summary["stages_count"] = len(stages)
        else:
            # 未完成的处理
            last = stages[-1]
            summary = {
                "entry_id": str(stages[0]["data"].get("entry_id")) if stages[0].get("data") else "",
                "trace_id": trace_id_filter or "",
                "canonical_id": target_canonical_id,
                "status": "pending" if last.get("status") != "error" else "error",
                "start_time": stages[0]["timestamp"],
                "stages_count": len(stages)
            }

        return jsonify({
            "status": "ok",
            "type": "detail",
            "canonical_id": target_canonical_id,
            "trace_id": trace_id_filter or summary.get("trace_id"),
            "summary": summary,
            "stages": stages
        })

    @app.route("/miniflux-ai/user/llm-calls", methods=["GET"])
    def get_llm_calls():
        """
        获取 LLM 调用记录列表。

        参数：
        - limit: 返回数量限制 (默认100, 最大500)
        - offset: 分页偏移
        - canonical_id: 按 canonical_id 过滤
        - trace_id: 按 trace_id 过滤
        - agent: 按 agent 名称过滤
        - status: 按状态过滤 (success/error)

        返回格式：
        {
          "status": "ok",
          "total": 150,
          "calls": [
            {
              "timestamp": "...",
              "trace_id": "...",
              "entry_id": "...",
              "canonical_id": "...",
              "agent": "summary",
              "stage": "preprocess",
              "status": "success",
              "duration_ms": 1500,
              "prompt_template": "...",
              "input_text": "...",
              "raw_response": "..."
            }
          ]
        }
        """
        import json

        # 解析参数
        limit_raw = request.args.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 100
        except ValueError:
            limit = 100
        if limit <= 0 or limit > 500:
            limit = min(max(limit, 1), 500)

        offset_raw = request.args.get("offset")
        try:
            offset = int(offset_raw) if offset_raw is not None else 0
        except ValueError:
            offset = 0
        if offset < 0:
            offset = 0

        canonical_id_filter = request.args.get("canonical_id", "").strip()
        trace_id_filter = request.args.get("trace_id", "").strip()
        agent_filter = request.args.get("agent", "").strip()
        status_filter = request.args.get("status", "").strip()

        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
            return jsonify({"status": "ok", "total": 0, "limit": limit, "offset": offset, "count": 0, "calls": []})

        # 收集所有 LLM 调用记录
        # 使用 (trace_id, entry_id, stage) 作为 key 来合并 start 和 complete 记录
        llm_calls = {}  # key -> call_data
        all_calls = []  # 最终列表

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        action = record.get("action", "")
                        stage = record.get("stage", "")

                        # 只处理 LLM 调用相关的记录
                        if action not in ("llm_call_start", "llm_call_complete", "llm_call_error"):
                            continue

                        trace_id = record.get("trace_id", "")
                        entry_id = str(record.get("entry_id") or "")
                        data = record.get("data") or {}

                        # 创建唯一 key
                        call_key = f"{trace_id}:{entry_id}:{stage}"

                        if action == "llm_call_start":
                            # 开始记录
                            canonical_id = data.get("canonical_id", "")
                            agent = data.get("agent", "")

                            llm_calls[call_key] = {
                                "timestamp": record.get("timestamp"),
                                "trace_id": trace_id,
                                "entry_id": entry_id,
                                "canonical_id": canonical_id,
                                "agent": agent,
                                "stage": stage,
                                "status": "pending",
                                "duration_ms": None,
                                "prompt_template": data.get("prompt_template", ""),
                                "input_text": data.get("input_text", ""),
                                "raw_response": "",
                            }

                        elif action == "llm_call_complete":
                            # 完成记录，更新状态
                            if call_key in llm_calls:
                                llm_calls[call_key]["status"] = "success"
                                llm_calls[call_key]["duration_ms"] = record.get("duration_ms")
                                llm_calls[call_key]["raw_response"] = data.get("raw_response", "")
                                # 更新 canonical_id（如果 start 时没有）
                                if not llm_calls[call_key]["canonical_id"]:
                                    llm_calls[call_key]["canonical_id"] = data.get("canonical_id", "")
                            else:
                                # 只有 complete 没有 start，创建独立记录
                                llm_calls[call_key] = {
                                    "timestamp": record.get("timestamp"),
                                    "trace_id": trace_id,
                                    "entry_id": entry_id,
                                    "canonical_id": data.get("canonical_id", ""),
                                    "agent": data.get("agent", ""),
                                    "stage": stage,
                                    "status": "success",
                                    "duration_ms": record.get("duration_ms"),
                                    "prompt_template": "",
                                    "input_text": "",
                                    "raw_response": data.get("raw_response", ""),
                                }

                        elif action == "llm_call_error":
                            # 错误记录
                            if call_key in llm_calls:
                                llm_calls[call_key]["status"] = "error"
                                llm_calls[call_key]["duration_ms"] = record.get("duration_ms")
                                llm_calls[call_key]["raw_response"] = data.get("error", "")
                            else:
                                llm_calls[call_key] = {
                                    "timestamp": record.get("timestamp"),
                                    "trace_id": trace_id,
                                    "entry_id": entry_id,
                                    "canonical_id": data.get("canonical_id", ""),
                                    "agent": data.get("agent", ""),
                                    "stage": stage,
                                    "status": "error",
                                    "duration_ms": record.get("duration_ms"),
                                    "prompt_template": "",
                                    "input_text": "",
                                    "raw_response": data.get("error", ""),
                                }

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        # 转换为列表
        all_calls = list(llm_calls.values())

        # 应用过滤
        if canonical_id_filter:
            all_calls = [c for c in all_calls if c["canonical_id"] == canonical_id_filter]
        if trace_id_filter:
            all_calls = [c for c in all_calls if c["trace_id"] == trace_id_filter]
        if agent_filter:
            all_calls = [c for c in all_calls if c["agent"] == agent_filter]
        if status_filter:
            all_calls = [c for c in all_calls if c["status"] == status_filter]

        # 按时间降序排序
        all_calls.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

        total = len(all_calls)
        page_calls = all_calls[offset:offset + limit]

        return jsonify({
            "status": "ok",
            "total": total,
            "limit": limit,
            "offset": offset,
            "count": len(page_calls),
            "calls": page_calls
        })

    @app.route("/miniflux-ai/user/llm-calls/duplicates", methods=["GET"])
    def get_llm_calls_duplicates():
        """
        查找同一 canonical_id 被多次调用 LLM 的情况。

        返回格式：
        {
          "status": "ok",
          "duplicates": [
            {
              "canonical_id": "...",
              "call_count": 3,
              "first_call": "...",
              "last_call": "...",
              "agents": ["summary", "translate"]
            }
          ]
        }
        """
        import json

        log_path = os.path.join("logs", "manual-process.log")
        if not os.path.exists(log_path):
            return jsonify({"status": "ok", "duplicates": []})

        # 按 canonical_id 聚合统计
        canonical_stats = {}  # canonical_id -> {count, first_call, last_call, agents}

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        action = record.get("action", "")

                        # 只统计 llm_call_start，避免 start 和 complete 重复计数
                        if action != "llm_call_start":
                            continue

                        data = record.get("data") or {}
                        canonical_id = data.get("canonical_id", "")

                        if not canonical_id:
                            continue

                        timestamp = record.get("timestamp", "")
                        agent = data.get("agent", "")
                        stage = record.get("stage", "")

                        if canonical_id not in canonical_stats:
                            canonical_stats[canonical_id] = {
                                "canonical_id": canonical_id,
                                "call_count": 0,
                                "first_call": timestamp,
                                "last_call": timestamp,
                                "agents": set(),
                            }

                        stats = canonical_stats[canonical_id]
                        stats["call_count"] += 1

                        if timestamp:
                            if stats["first_call"] > timestamp:
                                stats["first_call"] = timestamp
                            if stats["last_call"] < timestamp:
                                stats["last_call"] = timestamp

                        if agent:
                            stats["agents"].add(agent)
                        if stage and stage not in ("preprocess", "agent_process"):
                            pass
                        elif stage:
                            stats["agents"].add(stage)

                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        # 筛选出调用次数 > 1 的
        duplicates = []
        for stats in canonical_stats.values():
            if stats["call_count"] > 1:
                duplicates.append({
                    "canonical_id": stats["canonical_id"],
                    "call_count": stats["call_count"],
                    "first_call": stats["first_call"],
                    "last_call": stats["last_call"],
                    "agents": sorted(list(stats["agents"])),
                })

        # 按调用次数降序排序
        duplicates.sort(key=lambda x: x["call_count"], reverse=True)

        return jsonify({
            "status": "ok",
            "duplicates": duplicates
        })

    return app
