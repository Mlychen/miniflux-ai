import threading
import os
import uuid
from typing import cast

import miniflux
from flask import Flask, current_app, jsonify, request, redirect, send_from_directory

from app.infrastructure.miniflux_gateway import MinifluxGatewayError
from app.infrastructure.protocols import LLMRequestPoolProtocol
from app.infrastructure.ai_news_repository_sqlite import AiNewsRepositorySQLite
from app.infrastructure.entries_repository_sqlite import EntriesRepositorySQLite
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

    from app.interfaces.http.ai_news_publish import register_ai_news_publish_routes
    from app.interfaces.http.task_query import register_task_query_routes
    from app.interfaces.http.webhook_ingest import register_webhook_routes

    register_ai_news_publish_routes(app)
    register_webhook_routes(app)
    register_task_query_routes(app)

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

    return app
