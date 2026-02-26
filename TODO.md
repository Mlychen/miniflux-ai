# TODO

## P1（中优先级）


3. AI News 生成质量与稳定性提升（LLM 重试/降级 + 输入去重/分组/排序）  
   需求背景：当前 [generate_daily_news.py](file:///d:/Code/miniflux-ai/core/generate_daily_news.py) 直接拼接 entries.content，缺少去重/分组/排序，导致摘要噪声高、主题跳跃；LLM 失败会直接丢弃产出，影响稳定性与可用性。  
   可执行改进建议：在生成输入前按 url/title 去重，按 feed.category 或 site_url 分组并按 created_at 排序；对 LLM 调用加入有限重试与降级（例如失败时输出最小可用摘要或标题列表），保证即使部分失败也能产生可发布内容。
4. 触发链路稳定性治理（entries.json 锁拆分 + refresh_feed 语义文档化）  
   需求背景：entries.json 与 ai_news.json 默认共享同一把锁（见 [create_app](file:///d:/Code/miniflux-ai/myapp/__init__.py#L10-L29) 与 [json_storage.py](file:///d:/Code/miniflux-ai/common/json_storage.py#L1-L55)），高并发 webhook 写入会阻塞 AI News 读取/清理，导致请求堆积与超时；同时 refresh_feed 仅触发后台刷新，未明确延迟与调度行为，容易造成“触发=立刻可见”的误解。  
   可执行改进建议：拆分 entries 与 ai_news 的锁对象，降低互锁阻塞；在 README 运行指南中明确 refresh_feed 为后台触发、存在延迟与调度窗口，给出排查路径与期望时间范围。
5. 用户操作入口（User Actions Gateway）设计与实现  
   需求背景：目前仅有 webhook 和轮询两个系统级入口，缺少面向用户的统一控制通道。用户希望从 Miniflux 页面直接触发多种 AI 操作（单条处理、按订阅源配置 AI 白/黑名单、记录状态、动态修改提示词等），而不被 “entry 专用接口” 限制。  
   可执行改进建议：在 myapp 层新增 user_actions 模块，提供 `POST /miniflux-ai/user/actions` 统一入口，由前端通过 `action + params` 协议提交不同用户动作（如 `process_entry`、`update_agent_prompt`、`toggle_feed_agent` 等），路由内部根据 action 分发到对应用例；前端通过 Miniflux 自定义 JS 按需调用该入口，实现按钮、开关等用户操作与 miniflux-ai 的解耦与扩展。

## P2（中长期）

8. 引入可观察性指标（处理耗时、成功率、重复率）  
   需求背景：缺少核心链路可观测数据，难以评估处理效率与成本。
