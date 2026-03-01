import asyncio
from pathlib import Path
from typing import Any, cast

# 可选：抑制 browser-use 的冗余日志
# os.environ["BROWSER_USE_LOG_LEVEL"] = "error"

# 1. 设置安全的下载路径（避免使用默认的 /tmp）
downloads = Path.cwd() / "downloads"
downloads.mkdir(exist_ok=True)

# 2. 修补 BrowserProfile 以强制使用安全路径
# 注意：必须在导入 BrowserSession 之前进行修补，因为 session 模块在导入时可能会初始化默认 profile
try:
    from browser_use.browser.profile import BrowserProfile
    
    OriginalInit = BrowserProfile.__init__
    
    def PatchedInit(self, **data):
        # 如果未指定下载路径，强制注入安全路径
        if 'downloads_path' not in data or data.get('downloads_path') is None:
            data['downloads_path'] = downloads
        OriginalInit(self, **data)
        
    patched_profile = cast(Any, BrowserProfile)
    patched_profile.__init__ = PatchedInit
except ImportError:
    pass

async def main():
    from browser_use.browser.events import NavigateToUrlEvent
    from browser_use.browser.session import BrowserSession
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
        
        url = "http://192.168.5.23:8081/debug/"
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
        else:
            print("Failed to get page state or DOM is empty.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Closing browser...")
        # 4. 使用 kill() 而不是 close() 以确保进程完全退出
        await session.kill()

if __name__ == "__main__":
    asyncio.run(main())
