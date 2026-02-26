# TODO

## P0（高优先级）

1. 单入口 + webhook 缓冲 + 去重一并落地（实施文档）  
   设计文档：[IMPLEMENTATION_SINGLE_ENTRY.md](file:///d:/Code/miniflux-ai/IMPLEMENTATION_SINGLE_ENTRY.md) ✅ 已完成
   设计文档：[IMPLEMENTATION_SINGLE_ENTRY.md](file:///d:/Code/miniflux-ai/IMPLEMENTATION_SINGLE_ENTRY.md)

## P1（中优先级）

2. 路由与模块命名一致性重构并统一对外路由（webhook/ai_news）  
   需求背景：当前 webhook 入口在 [ai_summary.py](file:///d:/Code/miniflux-ai/myapp/ai_summary.py) 实际承担“入口+批处理”职责，而 ai_news 路由用于 RSS 输出，[ai_news.py](file:///d:/Code/miniflux-ai/myapp/ai_news.py) 却不体现“发布/投递”语义，导致新成员或调用方对边界误解。路由名与文件名不一致还会增加搜索与维护成本。  
   可执行改进建议：合并“模块重命名 + 对外路由统一”为一次实施，统一路由前缀与命名规范，同步更新引用与测试路径。实施文档：[IMPLEMENTATION_ROUTE_UNIFICATION.md](file:///d:/Code/miniflux-ai/IMPLEMENTATION_ROUTE_UNIFICATION.md)
3. AI News 生成质量与稳定性提升（LLM 重试/降级 + 输入去重/分组/排序）  
   需求背景：当前 [generate_daily_news.py](file:///d:/Code/miniflux-ai/core/generate_daily_news.py) 直接拼接 entries.content，缺少去重/分组/排序，导致摘要噪声高、主题跳跃；LLM 失败会直接丢弃产出，影响稳定性与可用性。  
   可执行改进建议：在生成输入前按 url/title 去重，按 feed.category 或 site_url 分组并按 created_at 排序；对 LLM 调用加入有限重试与降级（例如失败时输出最小可用摘要或标题列表），保证即使部分失败也能产生可发布内容。
4. 触发链路稳定性治理（entries.json 锁竞争缓解 + refresh_feed 语义与延迟指导）  
   需求背景：entries.json 与 ai_news.json 默认共享同一把锁（见 [create_app](file:///d:/Code/miniflux-ai/myapp/__init__.py#L10-L29) 与 [json_storage.py](file:///d:/Code/miniflux-ai/common/json_storage.py#L1-L55)），高并发 webhook 写入会阻塞 AI News 读取/清理，导致请求堆积与超时；同时 refresh_feed 仅触发后台刷新，未明确延迟与调度行为，容易造成“触发=立刻可见”的误解。  
   可执行改进建议：短期拆分 entries 与 ai_news 的锁对象，降低互锁阻塞；中期引入 webhook 缓冲队列与后台消费（参考 [IMPLEMENTATION_SINGLE_ENTRY.md](file:///d:/Code/miniflux-ai/IMPLEMENTATION_SINGLE_ENTRY.md)）；在 README 运行指南中明确 refresh_feed 为后台触发、存在延迟与调度窗口，给出排查路径与期望时间范围。

## P2（中长期）

8. 引入可观察性指标（处理耗时、成功率、重复率）  
   需求背景：缺少核心链路可观测数据，难以评估处理效率与成本。
