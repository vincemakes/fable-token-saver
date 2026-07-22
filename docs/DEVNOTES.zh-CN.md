# 开发笔记(v0.1.0 重命名前存档)

> **重命名前存档 / pre-rename archive:** 本文保留 2026-07 的原始
> `fable-token-saver` 路径、命令和模型叙事,仅用于复现实验,不是 Token Saver v2
> 的现行操作文档。当前仓库是
> <https://github.com/vincemakes/token-saver>。

> 本项目从 idea 到发布在一个 Claude Code session 内完成(2026-07-02 ~ 07-03,Fable 5 主循环)。
> 本文是该 session 的知识存档:目录地图、复现方法、实测结论、踩坑记录、后续方向。

## 目录地图

| 位置 | 内容 |
|---|---|
| `~/Desktop/devv/fable-token-saver` | 历史评测工作区路径(不是现行仓库安装说明) |
| `~/.claude/skills/fable-token-saver` | 历史 v0.1.0 本地安装路径,仅用于复现旧运行 |
| `~/.claude/skills/fable-token-saver-workspace/` | **评测数据全在这(不在 git 里,删 session 不影响)**:iteration-1(小任务×3×2)、iteration-2(大任务×2)、iteration-3(max 档 opus/sonnet)、iteration-4(埋雷调试赛)、各 run-iteration-*.sh、fixture-template、grade_mechanical.py 等 |
| `benchmarks/`(本仓库) | benchmark.json/md、触发评测集、`bughunt/`(埋雷源码 + 盲测试,可复现) |

## 如何复现 / 扩展评测

1. 每组条件 = 独立 headless 进程:`claude -p "<prompt>" --model <id> --dangerously-skip-permissions --output-format json`,输出 JSON 自带 `modelUsage` 分模型明细(in/out/cacheRead/cacheWrite/costUSD)——所有数字的来源,零估算
2. fixture 是自带 tsc+vitest 闸门的小型 pnpm 项目,git 初始化过(skill 依赖 `git diff`);每个 run 用全新拷贝
3. 对照组 prompt 相同,仅一句差异:with 组"invoke the fable-token-saver skill first",baseline 组"do not invoke any skills"
4. 调试赛的关键机制是**盲测试集**(`benchmarks/bughunt/hidden.test.ts`):被测方永远看不到,跑完注入 `tests/hidden/` 执行判分。埋雷 6 颗:半开区间双计费、逐行舍入漂移、内部引用泄漏、异步竞态丢更新、缓存不失效、数字键字典序
5. **额度代理指标 = 该模型名下的 costUSD**(单价对 in/out/cache 的加权与算力同构;官方额度公式不公开)

## 实测结论(v0.1.0 定稿)

- 小任务(<300 行):**负收益** +34~66% → 委托门槛写进 SKILL.md
- 大构建任务:lite −34% 额度且总费用最低;max(Opus 主循环)−88% 额度但总费用 +86%(额度套利)
- max 档主循环纪律:Opus 两次干净检查点(fable cacheRead=0);**Sonnet 抱顾问不放(3.7×),两头输** → 推荐 Opus 级
- 盲测调试赛:**6/6 vs 6/6 能力持平**;但判断密集型任务编排纯亏(2.2× 费用/3.9× 时间)→ "调试不触发"从直觉变数据
- 模型价目(2026-07):Fable $10/$50,Opus 4.8 $5/$25,Sonnet 5 $3/$15,Haiku 4.5 $1/$5(每百万 token)

## 踩坑记录(复现评测前必读)

1. **在 Claude Code 会话里 spawn `claude -p` 必须洗环境**(`env -i HOME=... PATH=...`):继承的 `CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH` 等变量会让子 CLI 放弃自刷 OAuth token,直接 401
2. **skill-creator 插件的 run_loop/run_eval 触发检测与 CLI 2.1.198 流事件不兼容**:96 次运行 0 触发,量化结果全部作废;真实触发要用活探针验证(直接 `claude -p` 自然语言问询 + grep 流输出里的 Skill 调用)
3. **SKILL.md description 硬上限 1024 字符**(package_skill 校验),写触发词前先算预算
4. **fixture 的 node_modules 千万别进 git**:会污染 `git diff`,直接破坏 skill 的 diff-only 审查流程
5. zsh 里 `echo ===` 会触发等号展开报错;macOS BSD sed 不支持 BRE 的 `\|`(脱敏管道用 python 别用 sed)
6. 后台单包派工会把 orchestrator 晾死(结果通知路由不回)→ SKILL.md 已写死"单包前台阻塞派工"
7. **agent 自判主循环模型不可靠**(2026-07-03 实测):系统 prompt 里的身份串("You are powered by …")可能是静态模板,不跟 `/model` 走;用户选 Opus 的 session 里 agent 自判成 Fable → 误入 lite 模式,整个 session 一次都没调 Fable 顾问,且该丢失完全静默(误判 max 会当场暴露=自己咨询自己,误判 lite 不会)→ SKILL.md 已加"Detect the mode before anything else"一节:信源排序(用户明说 > harness 模型 ID > 身份串)、不确定时默认 max、首行宣告检测结果、矛盾检测(用户措辞预设你之上有顾问时先确认)

## 后续方向(未做)

- **总费用交叉点**:>5,000 行的超大任务上验证 lite 的美元节省是否显著拉开(现在只有 −5%)
- **统计显著性**:所有结论均为单次运行(n=1 探针),关键数字值得跑 3-5 次取均值
- **其他模型组合**:埋雷 fixture 可直接复用于任意 `--model` 组合的能力对比
- 英文版推文/贴 HN;收集 issue 反馈迭代 v0.2

## 发布信息

- 当前仓库:https://github.com/vincemakes/token-saver(main,MIT)
- 历史 v0.1.0 仓库标识:`vincemakes/fable-token-saver`(只用于存档引用)
- Release v0.1.0 带 `.skill` 安装包;Social preview 已设(`media/og.png`,1280×640)
