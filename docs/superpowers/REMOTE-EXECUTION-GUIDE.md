# 远程电脑执行总指南

> 本文件:在远程电脑上执行 P1→P4 整条知识图谱改造线的总指南。随时可查。
> 最后更新:2026-07-05。分支:`feature/entity-graph-projection`。

---

## 一、先 sync + 看清当前状态

```bash
cd AIOne
git checkout feature/entity-graph-projection
git pull
git log --oneline -20          # 确认 P1/StepA/StepB/P3 的实现提交都在
```

## 二、执行顺序(严格按依赖,不能跳)

```
① e2e 验证(P3+StepB)  ← 先验证已完成的代码在真实服务下跑得通
        ↓ 通过
② P5(图洞察注入)       ← 依赖 StepB 的社区/god/surprising + P3 的 seed 匹配
        ↓ 完成
③ P4(CKP 图治理)       ← 依赖 P5 的 graph_community 表(读 cohesion)
```

⚠️ **P4 必须在 P5 之后**——它读 P5 写的 `graph_community`。顺序错了 P4 会降级(只 god 信号生效)。

> P1 / Step A / Step B / P3 的**实现代码已合入分支**;P5 / P4 是**计划已就绪、待执行**。e2e 是验证前四者真实运行正确,再进 P5/P4。

## 三、每个阶段怎么执行(subagent-driven,和之前一样)

每个计划文件头部都标了 sub-skill(`superpowers:subagent-driven-development` 或 `executing-plans`)。在远程电脑的 Claude Code 里:

```bash
cd AIOne && git pull
# 对当前阶段的计划文件,逐任务跑(子代理按 - [ ] 步骤一个个做,每 task 一提交)
```

每个计划都是 **TDD、每步完整代码、每步独立提交**。

## 四、阶段①:e2e 验证(现在就该做)

这不是写代码,是**验证已完成的 P3+StepB 在真实服务下对不对**(单测全是 mock 的)。

- runbook:`docs/superpowers/plans/2026-07-05-p3-stepb-e2e-verification-runbook.md`
- 关键步骤:启动 docker → 上传文档 → Neo4j Cypher 查社区/god/surprising → 重入库验稳定 → 直接探针脚本验 P3 的 `unified_search` 真的用了图扩展。
- **最该盯:B1 探针的 `source_marker` 输出**——fast 应见 `graph_1hop`、deep 应见 `community/god/surprising`。没有 = P3 在真实下没生效,要修而不是堆 P5/P4。

## 五、阶段②③:P5 / P4 执行

e2e 通过后,按计划文件逐个跑:

| 阶段 | 计划文件 | 任务数 |
|------|---------|-------|
| P5 洞察注入 | `docs/superpowers/plans/2026-07-05-p5-graph-insights-injection.md` | 8 |
| P4 CKP 图治理 | `docs/superpowers/plans/2026-07-05-p4-graph-driven-ckp-governance.md` | 6 |

每个跑完按计划末尾的 Task(N) 做手动 e2e。

## 六、通用执行注意(每个阶段都适用)

1. **pytest 必须带 `DATABASE_URL`**:`DATABASE_URL=sqlite:///./_t.db python -m pytest ...`(否则 import 时报错)。
2. **P4/P5 需 `pip install graphifyy`**(Step B 依赖,P5/P4 复用)——若远程还没装。
3. **那 14 个预存测试失败**不是新代码的锅(已在 P3 review 时双重证明:fail at pre-P3 commit + P3 未动其源文件),别被它们干扰;跑指定计划里的测试文件即可。
4. **提交 trailer**:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`(计划里每步都带了)。
5. **并发协调**:如果你在远程执行,我(主会话)这边就**不动这个分支**了,避免互相 push reject。需要 review 你推上来的结果时再叫我。

## 七、全部完成后的全景

| 阶段 | 状态 | 验证 |
|------|------|------|
| P1 全覆盖抽取 | ✅ 代码 | `2026-07-03-p1-task8-verification-runbook.md` |
| Step A 收尾 | ✅ 代码 | 含在 e2e runbook |
| Step B graphify 分析 | ✅ 代码 | **e2e 待跑**(`2026-07-05-p3-stepb-e2e-verification-runbook.md`) |
| P3 统一检索 | ✅ 代码 | **e2e 待跑**(同上) |
| P5 洞察注入 | 📋 计划就绪 | 计划含 e2e |
| P4 CKP 图治理 | 📋 计划就绪 | 计划含 e2e |

## 八、相关文档索引

**Specs(设计):**
- `docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`(主架构)
- `docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md`
- `docs/superpowers/specs/2026-07-05-p3-unified-graphrag-retrieval-design.md`
- `docs/superpowers/specs/2026-07-05-p5-graph-insights-injection-design.md`
- `docs/superpowers/specs/2026-07-05-p4-graph-driven-ckp-governance-design.md`

**Plans(执行计划):**
- `docs/superpowers/plans/2026-07-03-p1-universal-entity-extraction.md`
- `docs/superpowers/plans/2026-07-05-stepA-hardening-stepB-graphify-analysis.md`
- `docs/superpowers/plans/2026-07-05-p3-unified-graphrag-retrieval.md`
- `docs/superpowers/plans/2026-07-05-p5-graph-insights-injection.md`
- `docs/superpowers/plans/2026-07-05-p4-graph-driven-ckp-governance.md`

**Runbooks(验证):**
- `docs/superpowers/plans/2026-07-03-p1-task8-verification-runbook.md`
- `docs/superpowers/plans/2026-07-05-p3-stepb-e2e-verification-runbook.md`

---

## 现在最该做的一步

**在远程电脑跑阶段①的 e2e runbook**,把结果(尤其 B1 探针输出 + A3 社区/god)贴回主会话。通过 → 安心进 P5;不通过 → 针对性修,而不是盲目堆后面阶段。
