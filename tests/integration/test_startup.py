"""
端到端启动测试

测试启动流程中的关键配置匹配，防止因参数名或端口配置不一致导致启动失败。
"""

import ast
import inspect
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestViteProxyConfig:
    """测试前端代理配置与后端端口匹配"""

    def test_vite_proxy_config_matches_backend_port(self):
        """验证 vite.config.js 代理端口与后端默认端口一致"""
        vite_config_path = PROJECT_ROOT / "debug-ui" / "vite.config.js"
        config_path = PROJECT_ROOT / "app" / "infrastructure" / "config.py"

        # 读取 vite.config.js
        vite_content = vite_config_path.read_text(encoding="utf-8")

        # 提取代理目标端口
        # 格式: target: 'http://localhost:8081'
        proxy_match = re.search(r"target:\s*['\"]https?://[^:]*:(\d+)", vite_content)
        assert proxy_match, "无法从 vite.config.js 解析代理目标端口"
        vite_port = int(proxy_match.group(1))

        # 读取 config.py 获取默认端口
        config_content = config_path.read_text(encoding="utf-8")

        # 提取 debug_port 默认值
        # 格式: self.debug_port = debug_config.get('port', 8081)
        port_match = re.search(
            r"debug_port\s*=\s*debug_config\.get\s*\(\s*['\"]port['\"]\s*,\s*(\d+)",
            config_content,
        )
        assert port_match, "无法从 config.py 解析 debug_port 默认值"
        config_port = int(port_match.group(1))

        # 验证端口匹配
        assert (
            vite_port == config_port
        ), f"端口不匹配: vite.config.js 代理到 {vite_port}, config.py 默认端口 {config_port}"


class TestTaskWorkerParams:
    """测试 TaskWorker 参数名与调用匹配"""

    def test_task_worker_params_match_config(self):
        """验证 TaskWorker 参数名与 main.py 调用时匹配"""
        # 获取 TaskWorker.__init__ 的参数签名
        from app.application.worker_service import TaskWorker

        sig = inspect.signature(TaskWorker.__init__)
        worker_params = set(sig.parameters.keys())
        # 移除 self
        worker_params.discard("self")

        # 读取 main.py 中调用 TaskWorker 的代码
        main_path = PROJECT_ROOT / "main.py"
        main_content = main_path.read_text(encoding="utf-8")

        # 解析 main.py 中的 TaskWorker 调用
        # 查找 TaskWorker(...) 调用块
        tree = ast.parse(main_content)

        task_worker_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "TaskWorker":
                    task_worker_calls.append(node)

        assert len(task_worker_calls) > 0, "main.py 中未找到 TaskWorker 调用"

        # 检查第一个 TaskWorker 调用的参数
        call = task_worker_calls[0]
        call_params = set()
        for keyword in call.keywords:
            call_params.add(keyword.arg)

        # 验证调用中使用的参数名在 TaskWorker.__init__ 中存在
        for param in call_params:
            assert (
                param in worker_params
            ), f"参数 '{param}' 不在 TaskWorker.__init__ 签名中。有效参数: {worker_params}"

        # 特别检查 base_retry_delay_seconds 参数
        # 这是之前导致问题的参数
        assert "base_retry_delay_seconds" in worker_params, "TaskWorker 缺少 base_retry_delay_seconds 参数"
        assert (
            "base_retry_delay_seconds" in call_params
        ), "main.py 调用 TaskWorker 时缺少 base_retry_delay_seconds 参数"

    def test_config_field_matches_task_worker_param(self):
        """验证 Config 字段与 TaskWorker 参数的映射关系"""
        from app.infrastructure.config import Config

        # 创建一个测试配置
        test_config = Config.from_dict({
            "miniflux": {
                "task_workers": 4,
                "task_claim_batch_size": 10,
                "task_lease_seconds": 120,
                "task_poll_interval": 0.5,
                "task_retry_delay_seconds": 60,
            }
        })

        # 验证配置属性存在且能被 getattr 获取
        assert test_config.miniflux_task_workers == 4
        assert test_config.miniflux_task_claim_batch_size == 10
        assert test_config.miniflux_task_lease_seconds == 120
        assert test_config.miniflux_task_poll_interval == 0.5
        assert test_config.miniflux_task_retry_delay_seconds == 60


class TestBootstrap:
    """测试 bootstrap 函数创建的服务"""

    def test_bootstrap_creates_all_required_services(self):
        """验证 bootstrap 创建 my_flask 需要的所有服务"""
        # 创建测试配置文件
        config_content = """
miniflux:
  base_url: "http://localhost:8080"
  api_key: "test-key"

llm:
  provider: "openai"
  api_key: "test-llm-key"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            config_path = f.name

        try:
            # Mock 外部依赖
            with patch("main.MinifluxGateway") as mock_miniflux, patch(
                "main.LLMGateway"
            ) as mock_llm:
                # 配置 mock
                mock_miniflux_instance = MagicMock()
                mock_miniflux.return_value = mock_miniflux_instance
                mock_llm_instance = MagicMock()
                mock_llm.return_value = mock_llm_instance

                # 调用 bootstrap
                from main import bootstrap

                services = bootstrap(config_path)

                # 验证 RuntimeServices 包含所有必需字段
                assert services.config is not None
                assert services.logger is not None
                assert services.miniflux_client is not None
                assert services.llm_client is not None
                assert services.entry_processor is not None
                assert services.entries_repository is not None
                assert services.ai_news_repository is not None
                assert services.saved_entries_repository is not None

                # 验证 task_store 存在 (webhook 模式需要)
                assert services.task_store is not None, "task_store 不能为 None，webhook 模式需要它"

        finally:
            Path(config_path).unlink(missing_ok=True)


class TestFlaskStartup:
    """测试 Flask 启动"""

    def test_create_app_works_with_mocked_services(self):
        """验证 create_app 能用 mock 服务正常创建 Flask app"""
        from app.interfaces.http import create_app

        mock_config = MagicMock()
        mock_config.storage_sqlite_path = ":memory:"

        app = create_app(
            config=mock_config,
            miniflux_client=MagicMock(),
            llm_client=MagicMock(),
            logger=MagicMock(),
            entry_processor=MagicMock(),
            entries_repository=None,
            ai_news_repository=None,
            task_store=None,
        )

        assert app is not None
        # 验证一些基本路由存在
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        assert any("/miniflux-ai" in rule for rule in rules), "缺少 /miniflux-ai 路由"

    def test_flask_app_starts_on_random_port(self):
        """测试 Flask 应用能在随机端口启动并响应请求"""
        from app.interfaces.http import create_app

        # 找一个空闲端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        mock_config = MagicMock()
        mock_config.storage_sqlite_path = ":memory:"

        app = create_app(
            config=mock_config,
            miniflux_client=MagicMock(),
            llm_client=MagicMock(),
            logger=MagicMock(),
            entry_processor=MagicMock(),
            entries_repository=None,
            ai_news_repository=None,
            task_store=None,
        )

        # 在后台启动 Flask
        server_thread = threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False),
            daemon=True,
        )
        server_thread.start()

        # 等待服务器启动
        time.sleep(1)

        # 验证端口在监听
        import urllib.request

        try:
            # 尝试访问健康检查端点或根路径
            url = f"http://127.0.0.1:{port}/miniflux-ai/"
            req = urllib.request.Request(url, method="GET")
            # 即使返回 404 或其他状态，只要能连接就说明服务器在运行
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError:
            # 任何 HTTP 响应都说明服务器在运行
            pass
        except Exception as e:
            pytest.fail(f"无法连接到 Flask 服务器: {e}")


class TestEntryModeResolution:
    """测试入口模式解析"""

    def test_resolve_entry_mode_auto_with_webhook_secret(self):
        """auto 模式下有 webhook_secret 时应使用 webhook"""
        from main import resolve_entry_mode

        config = MagicMock()
        config.miniflux_entry_mode = "auto"
        config.miniflux_webhook_secret = "test-secret"

        result = resolve_entry_mode(config)
        assert result == "webhook"

    def test_resolve_entry_mode_auto_without_webhook_secret(self):
        """auto 模式下无 webhook_secret 时应使用 polling"""
        from main import resolve_entry_mode

        config = MagicMock()
        config.miniflux_entry_mode = "auto"
        config.miniflux_webhook_secret = None

        result = resolve_entry_mode(config)
        assert result == "polling"

    def test_resolve_entry_mode_webhook_requires_secret(self):
        """webhook 模式必须配置 webhook_secret"""
        from main import resolve_entry_mode

        config = MagicMock()
        config.miniflux_entry_mode = "webhook"
        config.miniflux_webhook_secret = None

        with pytest.raises(ValueError, match="webhook_secret"):
            resolve_entry_mode(config)

    def test_resolve_entry_mode_polling(self):
        """polling 模式"""
        from main import resolve_entry_mode

        config = MagicMock()
        config.miniflux_entry_mode = "polling"
        config.miniflux_webhook_secret = None

        result = resolve_entry_mode(config)
        assert result == "polling"

    def test_should_start_flask_for_webhook(self):
        """webhook 模式应启动 Flask"""
        from main import should_start_flask

        config = MagicMock()
        config.ai_news_schedule = None
        config.debug_enabled = False

        assert should_start_flask("webhook", config) is True

    def test_should_start_flask_for_ai_news_schedule(self):
        """有 ai_news_schedule 时应启动 Flask"""
        from main import should_start_flask

        config = MagicMock()
        config.ai_news_schedule = ["08:00"]
        config.debug_enabled = False

        assert should_start_flask("polling", config) is True

    def test_should_start_flask_for_debug(self):
        """debug 模式应启动 Flask"""
        from main import should_start_flask

        config = MagicMock()
        config.ai_news_schedule = None
        config.debug_enabled = True

        assert should_start_flask("polling", config) is True

    def test_should_not_start_flask_for_polling_without_schedule(self):
        """polling 模式无 schedule 时不应启动 Flask"""
        from main import should_start_flask

        config = MagicMock()
        config.ai_news_schedule = None
        config.debug_enabled = False

        assert should_start_flask("polling", config) is False


class TestTaskWorkerIntegration:
    """测试 TaskWorker 与 Flask 的集成"""

    def test_task_worker_starts_in_webhook_mode(self, tmp_path):
        """测试 TaskWorker 在 webhook 模式下正常启动"""
        from app.application.worker_service import TaskWorker
        from app.infrastructure.task_store_sqlite import TaskStoreSQLite

        # 创建 task store
        store = TaskStoreSQLite(path=str(tmp_path / "test_tasks.db"))

        # 创建 TaskWorker
        worker = TaskWorker(
            task_store=store,
            workers=1,
            poll_interval=0.1,
            base_retry_delay_seconds=1,
            logger=MagicMock(),
        )

        # 启动 worker
        processed_tasks = []

        def processor(task):
            processed_tasks.append(task)

        worker.start(processor)

        try:
            # 验证 worker 正在运行
            assert worker._running is True
            assert len(worker._threads) == 1

            # 创建一个测试任务
            store.create_task("test-1", {"entry_id": 1}, "trace-1")

            # 等待任务被处理
            time.sleep(0.5)

            # 验证任务被处理
            assert len(processed_tasks) > 0

        finally:
            worker.stop()
            assert worker._running is False
