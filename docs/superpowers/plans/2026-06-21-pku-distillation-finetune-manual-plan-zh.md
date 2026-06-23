# Prism PKU 小模型蒸馏微调手动实施计划

> 这是一份写给微调新手的手动实施计划。目标不是马上改 Prism 代码，而是先离线跑通「数据蒸馏 -> 小模型微调 -> 离线评估 -> 灰度替换」这一整条闭环。

## 1. 目标

Prism 当前知识治理链路里，`PersonalAssetUnit` 和 `DocumentChunk` 会通过主 LLM 抽取 PKU：

```text
PersonalAssetUnit / DocumentChunk
  -> PKU 抽取
  -> unit_type 分类
  -> JSON 校验
  -> PKU / CKP 治理入库
```

这部分任务有几个特点：

- 输出格式固定；
- 标签集合固定；
- 可以离线评估；
- 出错后可以回退主 LLM；
- 不直接影响最终回答表达质量。

所以它很适合用一个小模型来接管高频、稳定的子任务。

第一阶段目标：

```text
训练一个小模型，先做好 PKU unit_type 分类。
```

第二阶段目标：

```text
训练一个小模型，输出严格 PKU JSON。
```

最终替换目标：

```text
小模型优先抽取。
如果小模型输出合法且置信度足够，就使用小模型结果。
如果小模型输出不合法、置信度低、证据不可靠，就回退主 LLM。
```

## 2. 蒸馏和微调的区别

这两个词经常一起出现，但不是一回事。

```text
蒸馏：用强模型当老师，给训练样本生成答案。
微调：用这些样本继续训练小模型。
```

在 Prism 里就是：

```text
原始资产 / 文档块
  -> 当前主 LLM 生成 PKU 标签和 PKU JSON
  -> 清洗、过滤、人工抽查
  -> 得到训练集
  -> 微调 Qwen 小模型
  -> 小模型接管部分 PKU 抽取
```

所以这里的完整方案是：

```text
用蒸馏造数据，用微调训练模型。
```

## 3. 推荐模型

### 3.1 首选模型

```text
Qwen/Qwen3-4B-Instruct-2507
```

推荐理由：

- 4B 参数，中文能力和指令跟随能力比 1.7B 更稳；
- 适合严格 JSON 输出；
- 用 QLoRA 可以在单张消费级显卡上训练；
- Instruct 模型比 Base 模型更适合「输入 -> 结构化输出」任务；
- 对 Prism 这种中文知识治理任务更友好。

如果你有 RTX 3090 24GB，建议直接用这个模型，不需要退到 1.7B。

### 3.2 显存紧张时的备选模型

```text
Qwen/Qwen3-1.7B
```

适合：

- 只有 8GB 显存；
- 只训练 `unit_type` 分类器；
- 想先快速跑通微调流程。

不太适合：

- 完整 PKU JSON 抽取；
- 长输入；
- 对 JSON 稳定性要求很高的场景。

## 4. 推荐训练工具

推荐使用：

```text
LLaMA-Factory
```

原因：

- 支持 Qwen 系列；
- 支持 SFT；
- 支持 LoRA 和 QLoRA；
- 配置化训练，对新手友好；
- 不需要你从零写 Hugging Face Trainer。

这份计划默认你使用 LLaMA-Factory。

## 5. 最低训练配置

### 5.1 绝对最低配置：只训练 unit_type 分类器

这是最低可接受配置：

```text
GPU: NVIDIA RTX 3060 8GB / RTX 4060 8GB 或类似显卡
显存: 8GB
内存: 32GB
硬盘: 80GB 以上 SSD 空间
系统: Linux 或 WSL2
模型: Qwen3-1.7B
训练方式: QLoRA 4-bit
cutoff_len: 1024
batch size: 1
gradient_accumulation_steps: 8
lora_rank: 8
```

这个配置可以做：

- 12 类 `unit_type` 分类；
- 1000-3000 条样本的小规模实验；
- 新手流程验证。

这个配置不建议做：

- 完整 PKU JSON 抽取；
- 长文档块抽取；
- `cutoff_len` 超过 1024 的训练。

### 5.2 实用最低配置：训练 PKU JSON 抽取

```text
GPU: NVIDIA 16GB 显存起步，24GB 更推荐
显存: 16GB 最低，24GB 推荐
内存: 32GB 最低，64GB 推荐
硬盘: 120-150GB SSD 空间
系统: Linux 或 WSL2
模型: Qwen3-4B-Instruct-2507
训练方式: QLoRA 4-bit
cutoff_len: 1024 起步，稳定后再试 2048
batch size: 1
gradient_accumulation_steps: 8 或 16
lora_rank: 8 或 16
```

### 5.3 你的 RTX 3090 配置建议

RTX 3090 24GB 可以用来训练，而且非常适合这个任务。

推荐路线：

```text
GPU: RTX 3090 24GB
模型: Qwen/Qwen3-4B-Instruct-2507
训练方式: QLoRA 4-bit
任务 1: unit_type 分类
任务 2: PKU JSON 抽取
```

3090 第一轮推荐参数：

```yaml
model_name_or_path: Qwen/Qwen3-4B-Instruct-2507
finetuning_type: lora
quantization_bit: 4
cutoff_len: 2048
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.05
learning_rate: 8.0e-5
num_train_epochs: 3
fp16: true
```

说明：

- 3090 建议优先用 `fp16: true`；
- 如果你的环境确认 bf16 稳定，也可以试 `bf16: true`；
- 第一轮不要开太大 batch；
- 第一轮不要把 `cutoff_len` 直接拉到 4096；
- 先用 100 条样本做 smoke test，再跑完整训练。

### 5.4 不建议 CPU-only

不建议 CPU-only 训练。

CPU-only 理论上能跑很小实验，但会非常慢，不适合这个项目。没有 NVIDIA GPU 时，建议租云 GPU。

## 6. 第一件事：不要训练，先定义标签

你第一步不是安装训练框架，也不是下载模型。

第一步是写清楚 12 个 `unit_type` 到底是什么意思。

建议先创建一份标签说明：

```text
docs/ml/pku_unit_type_label_guide.md
```

标签定义如下：

| unit_type | 含义 | 正例 | 反例 |
|---|---|---|---|
| concept | 概念、对象、主题名 | "混合检索是个人知识库的核心能力。" | 一个完整流程 |
| definition | 对概念的定义 | "CKP 是对多个 PKU 归一后的稳定知识点。" | 个人观点 |
| claim | 观点、判断、结论 | "纯向量检索容易召回同主题噪声。" | 有具体实验上下文的测试结果 |
| method | 方法、流程、实现路径 | "先检索 CKP，再回溯 PKU 和原文证据。" | 必须遵守的规则 |
| rule | 规则、规范、要求 | "PKU 的 evidence 必须来自原文。" | 普通建议 |
| observation | 观察到的现象 | "检索结果里出现了多个同主题但无关的片段。" | 最终实验结论 |
| experiment_result | 实验、测试、实践结果 | "加入 metadata filter 后检索结果明显更准。" | 没有实验上下文的观点 |
| decision | 决策、取舍、已决定事项 | "第一版先不抽取 PKU relations。" | 一个待研究问题 |
| problem | 问题、缺陷、风险、阻塞 | "CKP 错误合并会污染知识图谱。" | 开放式疑问 |
| question | 疑问、待研究问题 | "是否需要为 CKP same_as 单独训练分类器？" | 已确认的问题 |
| pattern | 可复用经验模式 | "先用主 LLM 造数据，再微调小模型接管高频子任务。" | 单次决策 |
| constraint | 约束、边界、前提 | "只有 same_as 才允许合并到同一个 CKP。" | 普通观点 |

## 7. 手工标注 100 条样本

从 Prism 里选 100 条真实样本，手工判断它们的 `unit_type`。

优先来源：

```text
personal_knowledge_unit.statement
personal_asset_unit.summary
personal_asset_item.extracts.content
document parent chunk 中拆出的句子
```

目标不是凑数量，而是发现标签边界问题。

重点记录这些容易混淆的类型：

```text
claim vs observation
observation vs experiment_result
problem vs question
method vs rule
pattern vs method
concept vs definition
```

如果你自己标 100 条都经常犹豫，说明标签定义还不够清楚。这个时候不要训练，先修标签说明。

## 8. 阶段一：训练 unit_type 分类器

### 8.1 为什么先做分类器

因为它最简单、最容易评估，也最不容易污染知识库。

它可以替代或增强当前规则 fallback：

```text
_unit_type_from_unit_text
_unit_type_from_document_text
```

第一阶段不要让小模型直接抽完整 PKU，只让它判断：

```text
输入一条 statement
输出一个 unit_type
```

### 8.2 训练数据格式

使用 ShareGPT 风格 JSONL：

```json
{"messages":[{"role":"system","content":"你是 Prism 的 PKU 类型分类器。只能输出一个 unit_type，不要解释。允许的 unit_type: concept, definition, claim, method, rule, observation, experiment_result, decision, problem, question, pattern, constraint。"},{"role":"user","content":"请判断下面知识陈述的 unit_type：metadata filter 可以提升多项目个人知识库的检索准确性。"},{"role":"assistant","content":"experiment_result"}]}
```

### 8.3 数据量要求

最低：

```text
总样本数: 1200
每类至少: 50
验证集: 10%
测试集: 10%
```

推荐：

```text
总样本数: 3000
每类至少: 100
验证集: 10%
测试集: 10%
```

切分方式：

```text
正确做法:
  按 source_id 切分
  同一个文档或同一个资产单元的样本只能出现在一个集合里

错误做法:
  随机按行切分
  同一个来源的相似样本同时进入 train 和 test
```

### 8.4 蒸馏标签怎么来

用 Prism 当前主 LLM 当老师。

对每条 statement，让老师输出：

```json
{
  "unit_type": "claim",
  "confidence": 0.86,
  "reason": "short reason"
}
```

只保留：

```text
unit_type 在 12 个合法值中
confidence >= 0.75
statement 长度 >= 8
statement 长度 <= 1200
```

训练前至少人工抽查 100 条。

### 8.5 LLaMA-Factory 配置：unit_type

如果你用 RTX 3090，建议直接用 Qwen3-4B-Instruct-2507：

```yaml
model_name_or_path: Qwen/Qwen3-4B-Instruct-2507
stage: sft
do_train: true
finetuning_type: lora
template: qwen
dataset: prism_pku_unit_type
cutoff_len: 1024
learning_rate: 1.0e-4
num_train_epochs: 3
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.05
quantization_bit: 4
fp16: true
val_size: 0.1
logging_steps: 10
save_steps: 100
```

如果显存很稳，可以把：

```yaml
lora_rank: 16
lora_alpha: 32
```

### 8.6 unit_type 评估标准

必须看：

```text
Accuracy
Macro F1
每类 precision
每类 recall
混淆矩阵
非法输出率
```

最低通过线：

```text
Accuracy >= 0.85
Macro F1 >= 0.80
非法输出率 = 0
```

如果模型输出了 12 类以外的任何内容，都算错。

## 9. 阶段二：训练 PKU JSON 抽取模型

### 9.1 训练目标

输入一段资产单元内容，输出严格 JSON：

```json
{
  "pkus": [],
  "relations": []
}
```

第一版只要求抽 `pkus`。

不要一开始就训练 `relations`，因为关系抽取更难，也更容易制造脏数据。

### 9.2 输入示例

```text
任务：从下面 Prism 个人资产单元中抽取 PKU。只输出严格 JSON。

标题：RAG 检索实验记录
摘要：测试 metadata filter 对检索质量的影响。
正文：只用向量检索时召回了很多同主题但不相关的内容，加 metadata filter 后结果明显更准。
```

### 9.3 输出示例

```json
{
  "pkus": [
    {
      "local_id": "pku_1",
      "statement": "metadata filter 可以提升多项目个人知识库的检索准确性。",
      "normalized_statement": "metadata filter 可以提升多项目个人知识库的检索准确性。",
      "unit_type": "experiment_result",
      "keywords": ["metadata filter", "检索准确性"],
      "domains": ["个人知识库"],
      "entities": [],
      "concepts": ["混合检索"],
      "evidence": "加 metadata filter 后结果明显更准",
      "confidence": 0.86
    }
  ],
  "relations": []
}
```

### 9.4 数据量要求

最低：

```text
PersonalAssetUnit 抽取样本: 500
DocumentChunk 抽取样本: 第一版先不要做
验证集: 10%
测试集: 10%
```

推荐第一轮认真训练：

```text
PersonalAssetUnit 抽取样本: 1500-3000
DocumentChunk 抽取样本: 第二轮再加入
验证集: 10%
测试集: 10%
```

为什么先做 `PersonalAssetUnit`：

```text
内容更短
结构更干净
通常经过用户确认
比 document chunk 噪声少
更适合新手第一轮微调
```

### 9.5 老师数据怎么生成

对 `PersonalAssetUnit`，使用当前 Prism 的主 LLM prompt：

```text
build_asset_unit_pku_extraction_messages
```

对 `DocumentChunk`，以后再用：

```text
build_document_chunk_pku_extraction_messages
```

第一版只保留通过以下条件的老师输出：

```text
JSON 可以解析
pkus 是数组
每个 pku 有 statement
每个 pku 的 unit_type 在 12 个合法值中
每个 pku 有 evidence 或 evidence_span
confidence >= 0.70
evidence 能在输入文本中找到或近似找到
```

丢弃：

```text
Markdown 包裹输出
非法 unit_type
空 PKU
无法从原文支持的 PKU
过于空泛的 statement
只是标题的 statement
```

### 9.6 LLaMA-Factory 配置：PKU JSON 抽取

RTX 3090 推荐配置：

```yaml
model_name_or_path: Qwen/Qwen3-4B-Instruct-2507
stage: sft
do_train: true
finetuning_type: lora
template: qwen
dataset: prism_pku_extraction
cutoff_len: 2048
learning_rate: 8.0e-5
num_train_epochs: 3
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.05
quantization_bit: 4
fp16: true
val_size: 0.1
logging_steps: 10
save_steps: 100
```

如果爆显存：

```text
cutoff_len 降到 1024
lora_rank 降到 8
gradient_accumulation_steps 调到 16
per_device_train_batch_size 保持 1
```

## 10. 阶段三：离线评估

### 10.1 自动评估

每条输出都做程序校验：

```text
JSON 合法率 >= 98%
pkus 字段存在
unit_type 合法率 = 100%
statement 非空率 = 100%
evidence 非空率 >= 95%
evidence 原文命中率 >= 85%
平均 PKU 数量不能异常偏高
```

### 10.2 人工评估

随机抽 100 条模型输出，分三档：

```text
A: 可以直接入库
B: 轻微编辑后可用
C: 不可用或有风险
```

上线门槛：

```text
A + B >= 80
C <= 20
```

如果没有达到：

```text
不要接入 Prism
清洗数据
补充反例
缩小任务范围
重新训练
```

## 11. 阶段四：替换 Prism 链路

不要直接删除或替换主 LLM。

正确策略是：

```text
先调用小模型
  -> 解析 JSON
  -> 校验 schema
  -> 校验 unit_type
  -> 校验证据 evidence
  -> 检查 confidence
  -> 全部通过，使用小模型结果
  -> 任意失败，回退主 LLM
```

第一批替换：

```text
personal_asset_unit -> PKU extraction
```

第二批再考虑：

```text
document_chunk -> PKU extraction
```

原因：

```text
document_chunk 更长
document_chunk 噪声更多
document_chunk 更容易跨段缺上下文
```

## 12. 未来 Prism 接入位置

离线评估通过后，再考虑修改：

```text
backend/app/services/knowledge_governance.py
```

接入点：

```text
_extract_asset_unit_pkus_with_llm
_extract_document_chunk_pkus_with_llm
```

未来可以新增：

```text
_extract_asset_unit_pkus_with_small_model
_small_model_result_is_safe
```

伪代码：

```python
small_result = _extract_asset_unit_pkus_with_small_model(unit)
if _small_model_result_is_safe(small_result, source_text=unit.content or unit.summary):
    return small_result
return _extract_asset_unit_pkus_with_llm(unit)
```

校验器必须拒绝：

```text
非法 JSON
无 pkus
非法 unit_type
缺 statement
缺 evidence
evidence 不在原文
confidence 低于阈值
短输入抽出过多 PKU
```

第一版阈值建议：

```text
confidence >= 0.75
```

## 13. 手动执行清单

### Day 1：标签定义

- [ ] 写出 12 类 `unit_type` 标签说明。
- [ ] 从 Prism 真实数据中手工标注 100 条 statement。
- [ ] 记录容易混淆的类型。
- [ ] 修改标签说明，直到边界清楚。

### Day 2：构建 unit_type 数据集

- [ ] 从 Prism 导出候选 statement。
- [ ] 用主 LLM 给 statement 打 `unit_type` 标签。
- [ ] 过滤低置信度样本。
- [ ] 人工抽查至少 100 条。
- [ ] 生成 `train.jsonl`、`valid.jsonl`、`test.jsonl`。

### Day 3：训练 unit_type 分类器

- [ ] 安装 LLaMA-Factory。
- [ ] 下载 Qwen3-4B-Instruct-2507。
- [ ] 用 100 条样本跑 smoke test。
- [ ] 跑完整 QLoRA 训练。
- [ ] 在测试集上评估。
- [ ] 保存混淆矩阵。

### Day 4-5：构建 PKU 抽取数据集

- [ ] 对 confirmed `PersonalAssetUnit` 生成老师 PKU JSON。
- [ ] 过滤非法 JSON。
- [ ] 删除 Markdown 包裹输出。
- [ ] 删除 unsupported unit_type。
- [ ] 人工抽查至少 100 条。
- [ ] 生成抽取任务的 `train.jsonl`、`valid.jsonl`、`test.jsonl`。

### Day 6：训练 PKU JSON 抽取模型

- [ ] 用 100 条样本跑 smoke test。
- [ ] 确认模型能输出合法 JSON。
- [ ] 跑完整 QLoRA 训练。
- [ ] 评估 JSON 合法率。
- [ ] 做 100 条人工评审。

### Day 7：决定是否接入 Prism

- [ ] 如果指标通过，设计小模型 API wrapper。
- [ ] 如果指标失败，回到数据清洗。
- [ ] 离线指标未通过前，不替换主 LLM。

## 14. 最小成功标准

第一轮成功不是「完全替换主 LLM」。

第一轮成功是：

```text
unit_type 分类器:
  Accuracy >= 0.85
  Macro F1 >= 0.80
  非法输出率 = 0

PKU JSON 抽取:
  JSON 合法率 >= 98%
  unit_type 合法率 = 100%
  evidence 原文命中率 >= 85%
  人工评审 A+B >= 80%
```

只有达到这些标准后，才应该让 Prism 在知识治理链路里调用小模型。

## 15. 最重要的提醒

不要把训练看成第一步。

真正的第一步是：

```text
把标签定义清楚。
手工标注 100 条。
确认你自己能稳定区分 12 类。
```

否则微调只会把混乱学进去。

