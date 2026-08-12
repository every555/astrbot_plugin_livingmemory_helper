# 🧠 LivingMemory 辅助增强插件 v5.6.0

> 给春雪的「第二大脑」，让记忆管理变得像翻日记一样简单 (｀・ω・´)

> 🌟 **v5.6 重磅升级**：三层记忆金字塔可视化 (L1/L2/L3) + 记忆溯源链 + 路由修复

---

## 🎯 版本历史

| 版本 | 更新内容 |
|------|----------|
| v5.6.0 | 🔺 三层记忆金字塔可视化 (L1/L2/L3) + 记忆溯源链 + 路由冲突修复 |
| v5.5.2 | 监控数据修复（session_summary查询）+ 富配置面板扩展（检索/摘要/Dream Engine共11组26项）+ _conf_schema.json 全量同步 |
| v5.5.1 | 按需性能基准测试（BM25/DB/向量/混合 P95）+ 双索引健康面板 |
| v5.5 | 对话Digest页面（叙事摘要+轮次追踪+关键事实）+ 分层记忆统计（L0-L3）+ 双索引监控面板 |
| v5.4 | 会话线程追踪（provenance链）+ 手动生成摘要API + Summary页面生成按钮 |
| v5.3 | 会话摘要管理器（30分钟空闲自动触发）+ 跨会话连贯性 + Trace/Summary双页面 |
| v5.2 | 核心记忆索引 + 图增强召回 + 决策追踪 + 注入链重排（21/21测试全过） |
| v4.1.0 | 梦境引擎安全保底升级（备份/回滚/白名单prune/详细日志）+ 10+ bug修复 |
| v4.0 | 🎉 全新 WebUI Dashboard + 梦境引擎 + 知识图谱 + 8大WebUI页面 |
| v3.1 | 知识图谱模块（实体、关系、Schema、6个Agent Tools） |
| v3.0 | 4个Agent Tools、学习分类、优先级管理、功能请求记录 |
| v2.0 | 错误学习、记忆导出、提醒联动、冲突检测 |
| v1.0 | 基础时间轴、搜索、统计 |

---

## 🎯 我能做什么

### 📡 v3.0 新功能：Agent Tools

LLM可以**直接调用**这些工具，不需要通过命令：

| 工具 | 功能 | 使用场景 |
|------|------|----------|
| `haruyuki_recall_memory` | 回忆记忆 | 用户问"我们之前聊过什么" |
| `haruyuki_today_summary` | 今日摘要 | 用户问"今天聊了什么" |
| `haruyuki_search_memory` | 跨时间搜索 | 用户问"关于XX我们聊过几次" |
| `haruyuki_sentiment_trend` | 情感趋势 | 用户问"最近我们关系怎么样" |

### 🧠 v3.1 新功能：知识图谱 Agent Tools

LLM可以**直接调用**知识图谱：

| 工具 | 功能 | 使用场景 |
|------|------|----------|
| `haruyuki_ontology_create` | 创建实体 | "记住这个人物/项目/任务" |
| `haruyuki_ontology_query` | 查询实体 | "告诉我关于XX的详细信息" |
| `haruyuki_ontology_link` | 关联实体 | "把XX和XX关联起来" |
| `haruyuki_ontology_search` | 搜索实体 | "列出所有任务" |
| `haruyuki_ontology_related` | 相关查询 | "XX有哪些相关实体" |
| `haruyuki_ontology_stats` | 统计信息 | "知识图谱有多少数据" |

#### 🖥️ v4.0 全新 WebUI 仪表盘

插件页面 → `astrbot_plugin_livingmemory_helper` → 10个核心页面：

| 页面 | 图标 | 功能 |
|------|:----:|------|
| 📊 **仪表盘** | 首页 | 记忆统计卡片、30天趋势折线图、情感分布饼图、活跃度热力图、情感走势、梦境引擎状态、智能归并、智能报告 |
| 🔺 **记忆金字塔** | 三角形 | 🆕 v5.6: 三层记忆金字塔可视化（L1/L2/L3），SVG交互式层级展示，每层可折叠查看详细记忆列表，支持溯源链追踪 |
| 🕐 **时间轴** | 日历 | 按日期浏览记忆，支持今日/昨日/自定义日期/本周/上周/范围筛选 |
| 🔍 **智能检索** | 搜索 | 关键词搜索记忆，按标签/情感/时间筛选 |
| 📖 **避错账本** | 书本 | 查看/管理所有学习教训，按分类/优先级/标签筛选 |
| 🌙 **梦境日志** | 月亮 | 梦境引擎状态面板、手动唤醒/回滚、历史清洗日志、记忆归并建议 |
| 🕸 **关系图谱** | 网络 | 知识图谱可视化，力导向布局、节点点击查看详情、关系筛选 |
| ⏰ **提醒** | 闹钟 | 查看/管理所有定时提醒，支持创建/取消/自动扫描 |
| ⚙ **设置** | 齿轮 | 可视化配置所有插件参数 |
| 📡 **组装追踪** | 雷达 | v5.3: LLM注入链追踪，记录每次请求的注入数量/跳过原因/情感/意图 |
| 📝 **会话摘要** | 笔记 | v5.3: 会话级摘要，自动/手动生成，含话题/情感/时长/provenance链 |

#### 📊 仪表盘完整展示
```
📦 累计记忆 | 📝 今日新增 | 📖 学习教训 | 💾 数据库大小
📈 过去30天记忆趋势 → ECharts折线图
🎨 情感分布 → 情感饼图（积极/消极/中立）
🔥 记忆活跃度热力图 → 7天日历热力图
💫 近期情感走势 → 折线图
🔗 智能归并 → 相似记忆自动合并建议
🏷️ 热门标签 → 标签频率展示
🕐 最近记录 → 最新记忆卡片
📊 智能报告 → 日报/周报一键生成
📖 错误学习记录 | 🌙 历史梦境清洗日志 | ⏰ 记忆提醒
```

#### 🌙 梦境引擎 v4.1
```
状态：空闲 / 分析中 / 聚类中 / 清洗中 / 已完成
🛡️ 安全保底：白名单≥0.8 | 上限5% | 备份：✅
🔘 唤醒清洗引擎 | ⏪ 回滚备份
📋 历史梦境清洗日志（附详情查看）
```

---

## 🎮 命令功能

| 功能 | 命令 | 做什么 |
|------|------|--------|
| 🕐 记忆时间轴 | `/lmem-timeline today` | 像翻日记一样看每天的记忆 |
| 🧠 错误学习 | `/lmem-lessons` | 自动记住犯过的错，下次不会再犯 |
| 📤 记忆导出 | `/lmem-export md` | 导出成 Markdown/JSON/Obsidian 格式 |
| ⏰ 提醒联动 | `/lremind create` | 从记忆中提取约定，创建定时提醒 |
| 🔍 快捷命令 | `/记忆 关键词` | 比 /lmem search 更快的搜索入口 |
| 📊 统计报告 | `/lmem-report daily` | 每天/每周的记忆增长情况 |
| ⚡ 冲突检测 | `/lmem-conflicts` | 检测记忆里自相矛盾的内容 |
| 🔄 外部同步 | `/lmem-sync obsidian` | 同步记忆到 Obsidian 本地库 |
| 📝 功能请求 | `/lmem-feature` | 记录用户想要的功能 |
| 🧠 知识图谱 | `/ontology` | 管理实体、关系、Schema |

---

## 📦 安装

插件已放在 AstrBot 插件目录，重启 AstrBot 自动加载。

**依赖**：需要 `astrbot_plugin_livingmemory` 同时启用。

---

## 🧠 v3.0 学习分类系统

v3.0为错误教训新增了**学习分类**，让记忆更有条理：

| 分类 | 说明 | 示例 |
|------|------|------|
| `communication` | 沟通相关 | 说话方式、语气、表达 |
| `task` | 任务相关 | 做事流程、步骤、方法 |
| `tool` | 工具相关 | 工具使用、代码、配置 |
| `preference` | 偏好相关 | 用户喜好、习惯、风格 |
| `other` | 其他 | 无法归类的内容 |

**使用方式**：
```
/lmem-lessons                          → 查看所有教训
/lmem-lessons learning_type=tool       → 按分类筛选
/lmem-lessons priority=high            → 按优先级筛选
/lmem-lesson add 内容 learning_type=communication
```

---

## ⚡ 优先级管理

每条教训都有优先级，影响**自动注入**的顺序：

| 优先级 | 说明 | 自动注入 |
|--------|------|----------|
| `high` | 重要教训 | ✅ 优先注入 |
| `medium` | 一般教训 | ✅ 次要注入 |
| `low` | 不太重要 | ❌ 不自动注入 |

**优先级自动判断**：
- 包含"重要"、"必须"、"always"等词 → HIGH
- 包含"错误"、"失败"等词 → HIGH
- 其他 → MEDIUM

---

## 📝 功能请求记录

当用户提出功能建议时，可以记录下来：

```
/lmem-feature list                    → 查看所有功能请求
/lmem-feature add "希望能画漫画"       → 添加新功能请求
/lmem-feature done 5                  → 标记为已完成
/lmem-feature stats                   → 统计功能请求
```

---

## 📖 命令详解

### 🕐 记忆时间轴

```
/lmem-timeline today              → 今日时间轴
/lmem-timeline yesterday           → 昨天的记忆
/lmem-timeline 2026-06-30          → 指定某一天
/lmem-timeline this-week           → 本周汇总
/lmem-timeline last-week           → 上周汇总
/lmem-timeline range 06-01~06-30   → 日期范围
/lmem-timeline today detail        → 详细信息（重要性、标签、原文）
```

输出长这样：
```
📅 今日（周一）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 🕐 19:30   ⏰ 提醒橘子背单词
 🕐 19:16   📸 画了老婆大头照
 🕐 19:12   💬 橘子让老婆画猫耳女仆
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 📊 共 12 条 | 📈 最活跃时段: 19:00~20:00
```

### 🧠 错误学习系统

自动检测错误 + 记住教训：
- **自动触发**：当你说"不对"、"错了"等词时，春雪会悄悄记下来
- **工具报错**：如果工具调用失败了，自动记录原因
- **下次避免**：每次聊天前，会自动检查有没有相关经验

```
/lmem-lessons                          → 列出所有教训
/lmem-lessons tag=画图                 → 按标签筛选
/lmem-lessons learning_type=tool       → 按分类筛选
/lmem-lessons priority=high            → 按优先级筛选
/lmem-lesson 3                         → 查看第 3 条详情
/lmem-lesson add 内容                   → 手动添加教训
/lmem-lesson stats                     → 统计（学会了几条）
/lmem-lesson report                    → 学习成长报告
/lmem-lesson forget 3                  → 删除第 3 条
```

### 📤 记忆导出

```
/lmem-export md                          → 导出为 Markdown
/lmem-export json                        → 导出为 JSON
/lmem-export obsidian                    → 导出为 Obsidian 格式
/lmem-export md tags=画图,约定           → 只导出特定标签
/lmem-export all                         → 导出全部格式
```

文件保存在 `data/plugin_data/astrbot_plugin_livingmemory_helper/exports/`

### ⏰ 提醒联动

```
/lremind list                    → 查看所有提醒
/lremind create 5 "19:30"       → 从记忆 #5 创建提醒
/lremind cancel 1               → 取消提醒
/lremind auto on                → 开启自动扫描（每 5 分钟）
/lremind auto off               → 关闭自动扫描
```

### 🔍 快捷命令

```
/记住 橘子喜欢喝奶茶             → 快速保存（提示用 /lmem summarize）
/记忆 背单词                    → 搜索记忆
/忘记 关键词                    → 查 ID 然后用 /lmem forget 删除
/回忆 画图                      → 详细搜索（带时间和重要性）
```

### 📊 统计报告

```
/lmem-report daily              → 今日报告
/lmem-report weekly             → 本周报告
```

### ⚡ 冲突检测

```
/lmem-conflicts                 → 列出矛盾记忆
/lmem-conflict resolve 10 15    → 保留 #10，删除 #15
```

### 🧠 知识图谱

```
/ontology                                           → 查看帮助
/ontology create Person '{"name":"橘子"}'            → 创建实体
/ontology query person_202607130839                  → 查询实体
/ontology update person_202607130839 '{"age":25}'    → 更新实体
/ontology delete person_202607130839                  → 删除实体
/ontology list Task                                  → 列出所有Task
/ontology link person_001 has_owner project_001       → 创建关系
/ontology related person_001                          → 查询相关实体
/ontology stats                                       → 统计信息
/ontology export /path/to/export.jsonl               → 导出JSONL
/ontology import /path/to/import.jsonl               → 导入JSONL
```

```
/lmem-conflicts                 → 列出矛盾记忆
/lmem-conflict resolve 10 15    → 保留 #10，删除 #15
```

---

## 📡 Agent Tools 详解

### haruyuki_recall_memory
回忆过去的某段共同经历。
- **参数**：`query`（关键词）、`limit`（返回条数，默认5）
- **使用场景**：用户问"我们之前聊过什么"、"你记得XX吗"

### haruyuki_today_summary
获取今天（或指定日期）的共同经历概览。
- **参数**：`date`（日期，格式YYYY-MM-DD，默认今天）
- **使用场景**：用户问"今天聊了什么"、"我们今天做了什么"

### haruyuki_search_memory
跨时间段搜索记忆。
- **参数**：`query`（关键词）、`days`（回看天数，默认30）
- **使用场景**：用户问"关于XX我们聊过几次"、"最近XX话题的进展"

### haruyuki_sentiment_trend
了解最近的记忆情感趋势。
- **参数**：`days`（回看天数，默认14）
- **使用场景**：用户问"最近我们过得开心吗"、"最近状态怎么样"

---

## 🧠 v3.1 知识图谱 Agent Tools 详解

### haruyuki_ontology_create
创建知识图谱实体。
- **参数**：`entity_type`（实体类型）、`properties`（属性JSON）
- **实体类型**：Person、Project、Task、Event、Document、Note、Location、Organization、Goal、Custom
- **使用场景**：用户说"记住这个人/项目/任务"

### haruyuki_ontology_query
查询实体详情。
- **参数**：`entity_id`（实体ID）
- **返回**：实体的完整信息，包括所有关系
- **使用场景**：用户问"告诉我关于XX的详细信息"

### haruyuki_ontology_link
关联两个实体。
- **参数**：`from_id`（源实体ID）、`relation_type`（关系类型）、`to_id`（目标实体ID）
- **关系类型**：has_owner、has_member、has_task、blocks、depends_on、related_to、located_at、participates_in、created_by、Custom
- **使用场景**：用户说"把XX和XX关联起来"

### haruyuki_ontology_search
搜索实体。
- **参数**：`entity_type`（实体类型，可选）、`conditions`（条件JSON，可选）
- **使用场景**：用户问"列出所有任务"、"找到所有进行中的项目"

### haruyuki_ontology_related
获取实体的相关实体。
- **参数**：`entity_id`（实体ID）、`relation_type`（关系类型，可选）
- **使用场景**：用户问"XX有哪些相关实体"、"谁负责这个项目"

### haruyuki_ontology_stats
获取知识图谱统计信息。
- **参数**：无
- **返回**：实体总数、关系总数、类型分布
- **使用场景**：用户问"知识图谱有多少数据"

---

## ⚙️ WebUI 配置项

在 AstrBot 控制台 → 插件 → `astrbot_plugin_livingmemory_helper` → 配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `auto_inject_lessons` | true | 每次对话前自动注入教训 |
| `max_lessons_per_inject` | 2 | 每次最多注入几条 |
| `auto_scan_enabled` | false | 启动时自动开始扫描 |
| `embedding_api_key` | sk-xxx | 冲突检测用（留空则用规则检测） |

---

## 🔧 目录结构

```
astrbot_plugin_livingmemory_helper/
├── main.py                         # 插件入口（v5.4 组装追踪+会话摘要+WebUI路由）
├── metadata.yaml
├── _conf_schema.json               # WebUI 配置
├── README.md                       # 本文档
├── dream_engine.py                 # v4.0: 梦境引擎（清洗/聚类/情感分析/安全保底）
├── core/
│   ├── agent_tools.py              # v3.0: 4个Agent Tool实现
│   ├── ontology.py                 # v3.1: 知识图谱模块 + 6个Agent Tool
│   ├── error_learner.py            # 自建 SQLite 错误学习（v3.0: 学习分类+优先级）
│   ├── exporter.py                 # MD/JSON/Obsidian 导出
│   ├── reminder.py                 # 记忆→提醒联动
│   ├── reporter.py                 # 日报/周报统计
│   ├── conflict_detector.py        # 规则匹配冲突检测
│   ├── external_sync.py            # Obsidian 同步
│   ├── trace_manager.py            # v5.3: 组装追踪管理器
│   └── session_summary.py          # v5.3: 会话摘要管理器
├── utils/
│   ├── livingmemory_reader.py      # SQLite 读取工具
│   └── formatter.py                # 时间轴格式化
└── pages/
    └── dashboard/                  # v4.0: WebUI前端
        ├── index.html              # 10个页面的SPA（v5.3: +Trace +Summary）
        └── icon.png                # 插件图标
```

---

## ❓ 常见问题

**Q: Agent Tools 和命令有什么区别？**
A: Agent Tools 是给LLM调用的，当用户问"我们今天聊了什么"时，LLM会自动调用 `haruyuki_today_summary`。命令是给用户手动输入的。

**Q: 学习分类怎么用？**
A: 添加教训时可以指定分类：`/lmem-lesson add 内容 learning_type=tool`。系统也会自动判断分类。

**Q: 优先级影响什么？**
A: 优先级高的教训会优先注入到上下文，让LLM更容易记住重要的教训。

**Q: 功能请求记录在哪？**
A: 在SQLite数据库的 `feature_requests` 表中，用 `/lmem-feature` 命令查看。

**Q: Token 消耗？**
A: 几乎为零——注入教训时在 system prompt 末尾加 ~100 tokens，不影响正常对话。

**Q: 知识图谱和记忆系统有什么区别？**
A: 记忆系统是时间线式的，适合记录对话和事件；知识图谱是实体关系式的，适合管理结构化信息（人物、项目、任务之间的关系）。

**Q: 知识图谱数据存在哪？**
A: 在 `data/plugin_data/astrbot_plugin_livingmemory_helper/ontology.db`，SQLite格式。

**Q: 和 LivingMemory 冲突吗？**
A: 不冲突，只读 LivingMemory 数据库，错误教训和知识图谱写入自建 SQLite，不影响索引。

---

## 📝 更新日志

### v5.5.2 (2026-07-20)
- 🐛 修复监控页面 session_summary 查询（atom_type→metadata.atom_subtype）
- 🔧 富配置面板扩展：新增检索召回（Top-K/Max-K）、会话摘要（触发轮次）、Dream Engine（开关/故事时间/漂流瓶）共3组9项
- 📋 `_conf_schema.json` 全量同步至26个配置项
- 🔗 所有新配置项通过 `_LM_CONFIG_PATH_MAP` 映射到 LivingMemory 嵌套配置

### v5.5.1 (2026-07-19)
- ⏱️ 按需性能基准测试：BM25/DB/向量/混合检索 P95 延迟
- 🩺 双索引健康面板：BM25 FTS5 + 向量索引实时状态

### v5.5.0 (2026-07-19)
- 💬 对话Digest页面（春雪原创）：叙事摘要 + 轮次追踪 + 关键事实
- 📊 分层记忆统计（L0工作/L1活跃/L2情景/L3归档）
- 🩺 系统监控面板升级：原子记忆/图谱/BM25/向量全维度监控

### v5.4.0 (2026-07-19)
- 🔗 会话线程追踪：provenance链记录每条摘要的来源记忆ID
- ⚡ 新增「立即生成当前会话摘要」按钮 + `/api/summary/generate` 接口
- 📝 手动生成摘要：自动从documents表提取当前会话记忆→提取话题→判断情感→计算时长→写入memory_atoms
- 🐛 修复Summary页面数据为空的问题（自动触发条件未满足）

### v5.3.0 (2026-07-19)
- 📡 全新组装追踪（Trace）页面：记录每次LLM请求的注入链
  - 注入数量、跳过原因、情感标签、意图分类
  - 支持列表浏览 + 详情查看 + 统计面板
- 📝 全新会话摘要（Summary）页面：会话级记忆压缩
  - 30分钟空闲自动触发摘要生成
  - 摘要含话题提取、情感判断、会话时长、provenance溯源
  - 跨会话连贯性：新会话开始时自动注入上一次摘要
- 🔧 新增API：`/trace/list`、`/trace/detail`、`/trace/stats`、`/summary/list`、`/summary/detail`

### v5.2.0 (2026-07-19)
- 🧠 **核心记忆索引**：始终在线的顶层摘要，确保关键信息不丢失
- 🔗 **图增强召回**：利用知识图谱关系扩展记忆检索范围
- 📊 **决策追踪**：记录记忆系统的每一步决策过程
- 🔄 **注入链重排**：优化注入顺序，重要记忆优先（21/21测试全过）

### v4.1.0 (2026-07-18)
- 🛡️ 梦境引擎安全保底：新增备份/回滚/白名单prune/上限保护
- 🐛 修复热力图ECharts range格式错误
- 🐛 修复图表连锁崩溃（趋势图/情感饼图/热力图/情感走势）
- 🐛 修复日报SQL列名错误（content→text）
- 🐛 修复postMessage克隆问题
- 🐛 修复_read_body装饰器丢失
- 🐛 修复提醒通知守护进程逻辑
- 🐛 修复图谱节点详情API
- 🐛 修复Vue下划线变量名导致黑屏
- 🐛 修复时间解析分钟丢失
- 🐛 修复WebUI图表不显示（路由双重触发/Canvas尺寸）
- 🐛 修复confirm沙盒禁用提示
- 📝 新增详细梦境清洗日志

### v4.0 (2026-07-18)
- 🎉 **全新WebUI仪表盘**：8个核心页面全面升级
- 📊 仪表盘：统计卡片/30天趋势/情感饼图/热力图/情感走势
- 🌙 梦境引擎：状态面板/手动唤醒/回滚备份/历史日志
- 🕸 知识图谱：可视化展示/节点详情/关系筛选
- 🔗 智能归并（P1-1）：相似记忆自动检测合并
- 🕐 全新时间轴页面（按日期浏览）
- 🔍 智能检索页面（关键词+标签+情感筛选）
- 📖 避错账本页面（学习教训管理）
- ⏰ 提醒管理页面（创建/取消/自动扫描）
- ⚙ 可视化设置页面
- 📊 智能报告（日报/周报一键生成）
- ✨ 梦境引擎：记忆清洗/聚类/情感分析/主动告知
- ✨ 增强上下文注入（注入近期记忆片段）

### v3.1 (2026-07-13)
- 🧠 新增知识图谱模块（基于Ontology设计）
- ✨ 支持实体管理（Person、Project、Task、Event等10种类型）
- ✨ 支持关系管理（has_owner、has_task、depends_on等10种类型）
- ✨ 支持Schema验证（必填字段、枚举、禁止字段）
- ✨ 新增6个知识图谱Agent Tools
- ✨ 新增 `/ontology` 命令
- ✨ 支持JSONL导入导出

### v3.0 (2026-07-13)
- ✨ 新增4个Agent Tools（recall、today、search、sentiment）
- ✨ 新增学习分类系统（communication、task、tool、preference、other）
- ✨ 新增优先级管理（high、medium、low）
- ✨ 新增功能请求记录
- ✨ 新增UI Settings Bridge
- ✨ 增强上下文注入（注入近期记忆片段）

### v2.0 (2026-07-12)
- ✨ 新增错误学习系统
- ✨ 新增记忆导出（MD/JSON/Obsidian）
- ✨ 新增提醒联动
- ✨ 新增冲突检测
- ✨ 新增统计报告

### v1.0 (2026-07-11)
- 🎉 初始版本
- ✅ 记忆时间轴
- ✅ 快捷搜索
