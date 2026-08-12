# 记忆大家庭 · 生态蓝图 v2.1

> 日期：2026-08-04 ｜ 状态：已获橘子批准，分阶段实现中
> 定位：v2.0（记忆生态核心引擎）之后的家庭协作层——让所有工具从"独立服务"变成"一家人"

## 家训（橘子钦定，最高优先级）

1. **记忆永不删除**
2. **任何记忆永远可调用**（归档 ≠ 锁死，查询路径零拦截）
3. **归档只是收进相册，不是锁进保险柜**（检索降权不排除）

## 成员（22 位家人）

- **八件套**：recall / today / search / sentiment / reminder / trace / reinforce / knowledge
- **六件套**：ontology_create / query / link / search / related / stats
- **v2 五兄弟**：causal_chain / conflict_check / profile / prophecy / expression
- **侧写入**：memory_search / memory_memorize
- **后台团**：EmotionEngine（温度计）/ ErrorLearner（记错本）/ MemoryReporter（秘书）/ Exporter（档案员）/ ExternalSync（邮差）/ CodeChecker（体检医生）/ F7冲突检测（判官）
- **新家人**：归档员（相册管理员）★v2.1 新增
- **出局**：梦境引擎 DreamEngine（会删除记忆，坏蛋）

## §2 A. 反馈回路（家的温度）——10 条亲情线

| 线 | 谁→谁 | 机制 |
|---|---|---|
| A1 | 预言→画像 | 预言应验/失败 → 修正画像置信度 |
| A2 | 冲突→预言 | 冲突确认 → 重估相关预言 |
| A3 | 画像→表达 | 画像变化 → 表达联动（v2 已有基础，补双向） |
| A4 | 因果→预言 | 新因果链 → 自动触发预言 |
| A5 | 情感→画像 | EmotionEngine 情感趋势 → 反哺画像 |
| A6 | 预言→提醒 | 预言到期 → 自动转 reminder |
| A7 | 预言→recall | 预言回溯 → 用 recall 查证 |
| A8 | 冲突→知识 | 确认的冲突 → 沉淀为知识 |
| A9 | 教训→知识 | error_learner 教训 → 毕业为知识 |
| A10 | 归档→例会 | 归档候选 → 上报家庭例会 |

**机制：事件总线（松耦合，家人之间"说一声"不直接命令）**

## §3 B. 角色分工（家的结构）

- 记忆库=祖屋 ｜ 画像=妈妈 ｜ 预言家=爱猜的孩子 ｜ 冲突=判官 ｜ 因果链=族谱先生 ｜ reminder=管家 ｜ knowledge=老教师 ｜ error_learner=记错本 ｜ emotion=温度计 ｜ reporter=秘书 ｜ 归档员=相册管理员
- 存储：`family_roles` 表 + 家庭图谱

## §4 C. 家庭例会（家的日常）

- 每日定时（复用预言回溯 asyncio 调度机制）
- 每位家人汇报：画像更新/预言验证/冲突/因果/情感趋势/归档候选/知识毕业候选
- 产出：家庭日报（`family_reports` 表），主动推送橘子
- **例会第一个议题：归档候选审批**（C 混合模式）

## §5 归档员（新家人）

- 触发：C 混合模式——自动扫描沉睡候选（30 天未访问 + 低访问次数）→ 例会汇报 → 橘子确认 → 标记 archived
- 铁律：永不删除 / 永远可调用 / 检索降权不排除

## §6 数据模型（v2_memory.db 新增 4 表）

- `feedback_log`：亲情线流水（谁→谁、类型、结果、时间）
- `family_roles`：家人身份（工具名、角色、职责、协作对象）
- `family_reports`：家庭日报（日期、各家人统计、归档候选、状态）
- `archive_candidates`：归档候选（记忆ID、沉睡天数、状态 pending/confirmed/archived）

## §7 工具接口

- 新增：`haruyuki_family_status`（家庭总览）/ `haruyuki_family_meeting`（例会/日报）/ `haruyuki_archive`（归档审批）
- 扩展钩子：prophecy 到期→reminder、conflict 确认→预言重估、emotion 趋势→画像

## §8 分阶段实现（D3 路线：设计先行、实现分批）

```
Phase 1 → 反馈回路（A1-A10 + 事件总线 + feedback_log）
Phase 2 → 归档员（扫描→例会→确认→归档 + archive_candidates）
Phase 3 → 角色分工（family_roles + 家庭图谱）
Phase 4 → 家庭例会（调度 + 日报 + 推送 + family_reports）
```

## 实现守则（橘子指示）

- 一步到位（最终全部完成），但一步一步来（每步扎实可验证）
- 多思考、多验证、多用工具、了解全局、跳出固定思维
- 设计先行、审批后实现；每个 Phase 独立可测
