# Miniflux AI 调试指南

本文档记录了在受限环境（如 Trae IDE、Docker 容器）中使用 `browser-use` 进行调试和自动化操作的最佳实践。

## 浏览器自动化 (browser-use)

在沙箱或容器化环境中运行 `browser-use` 时，可能会遇到权限错误（如 `/tmp` 目录不可写）或浏览器启动失败。

### 核心问题与解决方案

1.  **路径权限问题**：`browser-use` 默认尝试在 `/tmp` 目录下创建配置和下载文件夹。在 Windows 或受限容器中，这会导致 `PermissionError`。
    *   **解决**：必须通过 `downloads_path` 参数显式指定一个当前用户可写的目录（如项目内的 `downloads/`）。
2.  **沙箱与安全性**：默认情况下 Chromium 使用沙箱隔离进程。在某些容器中（如 Trae 终端），嵌套沙箱会导致启动失败。
    *   **解决**：通常建议在容器内使用 `chromium_sandbox=False`。但在 Trae 中，我们发现只要解决了路径问题，`chromium_sandbox=True` (启用沙箱) 也是可以正常工作的，且更安全。
3.  **进程退出卡死**：`session.close()` 有时无法完全释放资源（特别是 WebSocket 连接），导致脚本执行结束后进程不退出。
    *   **解决**：使用 `session.kill()` 强制终止浏览器进程和清理资源。

### 标准使用代码

请使用以下模式初始化 `BrowserSession`，以确保在所有环境下的兼容性。

**注意**：
*   **Monkeypatch 风险**：代码使用了 Monkeypatch 来修改 `BrowserProfile.__init__`。这依赖于库的内部实现，如果 `browser-use` 更新更改了此方法签名，可能需要调整。
*   **服务检查**：在运行前，请确保目标服务（如 Miniflux AI）已在本地启动（通常是 `uv run python main.py`）。

```python
import asyncio
import os
from pathlib import Path

# 可选：抑制 browser-use 的冗余日志
# os.environ["BROWSER_USE_LOG_LEVEL"] = "error"

# 1. 设置安全的下载路径（避免使用默认的 /tmp）
downloads = Path.cwd() / "downloads"
downloads.mkdir(exist_ok=True)

# 2. 修补 BrowserProfile 以强制使用安全路径
# 注意：必须在导入 BrowserSession 之前进行修补，因为 session 模块在导入时可能会初始化默认 profile
try:
    import browser_use.browser.profile
    from browser_use.browser.profile import BrowserProfile
    
    OriginalInit = BrowserProfile.__init__
    
    def PatchedInit(self, **data):
        # 如果未指定下载路径，强制注入安全路径
        if 'downloads_path' not in data or data.get('downloads_path') is None:
            data['downloads_path'] = downloads
        OriginalInit(self, **data)
        
    BrowserProfile.__init__ = PatchedInit
except ImportError:
    pass

# 3. 导入核心组件
from browser_use.browser.session import BrowserSession
from browser_use.browser.events import NavigateToUrlEvent

async def main():
    print("Initializing BrowserSession...")
    
    # 初始化 Session
    session = BrowserSession(
        chromium_sandbox=True,   # 尝试启用沙箱以提高安全性（如果失败可改为 False）
        downloads_path=downloads, # 必须指定，配合上面的 Patch 确保万无一失
        headless=True            # 无头模式，适合服务器/终端环境
    )
    
    try:
        print("Starting browser...")
        await session.start()
        
        # 替换为实际要测试的 URL
        url = "http://127.0.0.1:8081/debug/"
        print(f"Navigating to {url}...")
        
        # 导航到目标页面
        await session.event_bus.dispatch(NavigateToUrlEvent(url=url))
        await asyncio.sleep(5) # 等待页面加载
        
        # 获取页面状态和内容
        print("Getting page state...")
        state = await session.get_browser_state_summary()
        
        if state and state.dom_state:
            print("\n--- Page Content ---\n")
            print(state.dom_state.llm_representation())
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing browser...")
        # 4. 使用 kill() 而不是 close() 以确保进程完全退出
        await session.kill()

if __name__ == "__main__":
    asyncio.run(main())
```

### 已知限制与注意事项

1.  **CLI 不可用**：
    `browser-use` 提供的命令行工具（如 `browser-use open ...`）无法应用上述的路径修补（Monkeypatch）。在受限环境中直接运行 CLI 几乎肯定会因尝试写入 `/tmp` 而失败。请务必编写 Python 脚本来调用。

2.  **临时文件清理**：
    上述脚本会在项目根目录创建 `downloads/` 文件夹。这些文件不会自动删除，建议定期手动清理或在脚本中添加清理逻辑。

3.  **网络连接**：
    如果在容器内访问宿主机服务，请使用宿主机 IP（如 `192.168.x.x`）而不是 `localhost`，除非使用了 host 网络模式。

## Debug UI 最小验收（任务排障）

打开 `http://127.0.0.1:8081/debug/` 后，建议按顺序确认：

1. `任务排障` 面板点击“加载分组”，能返回失败分组数据。
2. 点击某个分组“查看任务”，能看到任务样本列表。
3. 输入 `task_id` 点击“查看任务详情”，能返回单任务详情。
4. 点击“按筛选重入队”“重入队该组”或“重入队任务”，响应返回 `status=ok` 且 `requeued` 变化符合预期。
