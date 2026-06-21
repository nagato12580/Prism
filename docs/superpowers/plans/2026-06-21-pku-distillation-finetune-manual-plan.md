# Prism PKU Distillation Fine-Tuning Manual Plan

> This is a manual execution plan for a beginner-friendly PKU distillation and fine-tuning workflow. It does not require changing Prism code until the offline model passes evaluation.

## Goal

Train a small model to handle part of Prism's PKU governance pipeline:

```text
PersonalAssetUnit / DocumentChunk
  -> PKU extraction
  -> unit_type classification
  -> JSON validation
  -> Prism governance settlement
```

The first milestone is not to replace the main LLM. The first milestone is to prove that a small fine-tuned model can beat the current rule fallback on `unit_type` classification and produce valid PKU JSON on offline samples.

## Key Idea

Use distillation to create training data, then use fine-tuning to train the small model.

```text
Distillation:
  Existing main LLM acts as teacher
  Teacher generates PKU labels and PKU JSON

Fine-tuning:
  Small model acts as student
  Student learns to imitate the cleaned teacher outputs
```

In this plan:

```text
Teacher model: current Prism main LLM
Student model: Qwen3-4B-Instruct-2507 first choice, Qwen3-1.7B fallback
Training method: LoRA or QLoRA SFT
Training tool: LLaMA-Factory
```

## Recommended Model

### First Choice

```text
Qwen/Qwen3-4B-Instruct-2507
```

Why:

- Stronger Chinese and instruction-following ability than 1.7B.
- Better suited for strict JSON PKU extraction.
- Small enough for QLoRA on a single consumer GPU.
- The instruct variant is better for "input -> structured output" tasks than a base model.

Use this if you have at least a 16 GB NVIDIA GPU, or can rent a 24 GB GPU.

### Minimum Fallback

```text
Qwen/Qwen3-1.7B
```

Why:

- Easier to train on an 8 GB GPU.
- Good enough for the first `unit_type` classifier.
- Less reliable for full PKU JSON extraction.

Use this if your local GPU only has 8 GB VRAM.

## Minimum Hardware Configuration

### Absolute Minimum: Only Train `unit_type`

This is the lowest configuration I would still consider practical.

```text
GPU: NVIDIA RTX 4060 8GB, RTX 3060 8GB, or similar
VRAM: 8 GB
System RAM: 32 GB
Disk: 80 GB free SSD
OS: Linux or WSL2 strongly preferred
Model: Qwen3-1.7B
Training: QLoRA 4-bit
cutoff_len: 1024
batch size: 1
gradient_accumulation_steps: 8
lora_rank: 8
```

What this can do:

- Train a 12-class `unit_type` classifier.
- Run small experiments with 1000-3000 examples.

What this should not do:

- Do not start with full PKU JSON extraction on this setup.
- Do not use long document chunks.
- Do not set `cutoff_len` above 1024 at first.

### Practical Minimum: Train PKU JSON Extraction

```text
GPU: NVIDIA RTX 4060 Ti 16GB, RTX 4080 16GB, RTX 3090 24GB, RTX 4090 24GB, A10 24GB, L4 24GB
VRAM: 16 GB minimum, 24 GB recommended
System RAM: 32 GB minimum, 64 GB recommended
Disk: 120-150 GB free SSD
OS: Linux or WSL2
Model: Qwen3-4B-Instruct-2507
Training: QLoRA 4-bit
cutoff_len: 1024 first, then 2048 if stable
batch size: 1
gradient_accumulation_steps: 8 or 16
lora_rank: 8 or 16
```

What this can do:

- Train `unit_type`.
- Train a first PKU JSON extraction model.
- Handle asset-unit inputs reliably.

What this should not do yet:

- Do not train on full long documents.
- Do not require PKU relations in the first version.
- Do not train with `cutoff_len` 4096 until the 2048 run is stable.

### Comfortable Setup

```text
GPU: RTX 4090 24GB, RTX 3090 24GB, A5000 24GB, L40S 48GB, A100 40GB/80GB
VRAM: 24 GB or higher
System RAM: 64 GB
Disk: 200 GB free SSD
Model: Qwen3-4B-Instruct-2507
Training: QLoRA or LoRA
cutoff_len: 2048-4096
batch size: 1-2
gradient_accumulation_steps: 8
lora_rank: 16
```

This is the setup I recommend if you rent cloud GPU time. One RTX 4090 24GB is enough for the first serious version.

### CPU-Only

Do not use CPU-only training for this project.

CPU-only can technically run tiny experiments, but it will be too slow and frustrating. If you do not have an NVIDIA GPU, rent a cloud GPU for training.

## What To Do First

Do not start training immediately.

Your first work item is to define the label system and produce a tiny gold sample.

### Step 1: Write the 12 Label Definitions

Create a local notes file outside the model training dataset, for example:

```text
docs/ml/pku_unit_type_label_guide.md
```

Use this label guide:

| unit_type | Meaning | Positive Example | Negative Example |
|---|---|---|---|
| concept | A concept, object, or topic name | "混合检索是个人知识库的核心能力。" | A full process or rule |
| definition | Definition of a concept | "CKP 是对多个 PKU 归一后的稳定知识点。" | A personal opinion |
| claim | A claim, judgment, or conclusion | "纯向量检索容易召回同主题噪声。" | A measured test result |
| method | A method, workflow, or implementation approach | "先检索 CKP，再回溯 PKU 和原文证据。" | A mandatory rule |
| rule | A rule, standard, or requirement | "PKU 的 evidence 必须来自原文。" | A soft suggestion |
| observation | An observed phenomenon | "检索结果里出现了多个同主题但无关的片段。" | A final experiment conclusion |
| experiment_result | A concrete test or experiment result | "加入 metadata filter 后检索结果明显更准。" | A general claim without test context |
| decision | A decision or chosen direction | "第一版先不抽取 PKU relations。" | A question |
| problem | A problem, defect, risk, or blocker | "CKP 错误合并会污染知识图谱。" | An open research question |
| question | A question or unknown to investigate | "是否需要为 CKP same_as 单独训练分类器？" | A known issue |
| pattern | A reusable experience pattern | "先用主 LLM 造数据，再微调小模型接管高频子任务。" | A one-off decision |
| constraint | Boundary, precondition, or limitation | "只有 same_as 才允许合并到同一个 CKP。" | A normal claim |

### Step 2: Manually Label 100 Examples

Pick 100 real statements from Prism data and label them by hand.

Good sources:

```text
personal_knowledge_unit.statement
personal_asset_unit.summary
personal_asset_item.extracts.content
document parent chunk sentences
```

Do this before using teacher LLM labels. If you cannot label them consistently, the model cannot learn them consistently.

### Step 3: Record Confusing Pairs

Write down examples that are hard to distinguish:

```text
claim vs observation
observation vs experiment_result
problem vs question
method vs rule
pattern vs method
concept vs definition
```

Update the label guide until these boundaries are clear.

## Phase 1: Train `unit_type` Classifier

### Purpose

This is the safest first model. It replaces weak local rules such as:

```text
_unit_type_from_unit_text
_unit_type_from_document_text
```

It does not yet replace PKU extraction.

### Training Data Shape

Use ShareGPT-style JSONL:

```json
{"messages":[{"role":"system","content":"你是 Prism 的 PKU 类型分类器。只能输出一个 unit_type，不要解释。允许的 unit_type: concept, definition, claim, method, rule, observation, experiment_result, decision, problem, question, pattern, constraint。"},{"role":"user","content":"请判断下面知识陈述的 unit_type：metadata filter 可以提升多项目个人知识库的检索准确性。"},{"role":"assistant","content":"experiment_result"}]}
```

### Data Requirements

Minimum:

```text
Total examples: 1200
Per class: at least 50
Validation: 10%
Test: 10%
```

Recommended:

```text
Total examples: 3000
Per class: at least 100
Validation: 10%
Test: 10%
```

Split by source, not by row:

```text
Correct:
  all examples from source_id=A go to train
  all examples from source_id=B go to test

Wrong:
  examples from the same document appear in both train and test
```

### Teacher Data Generation

Use current Prism main LLM as teacher.

For each raw statement, ask the teacher to output:

```json
{
  "unit_type": "claim",
  "confidence": 0.86,
  "reason": "short reason"
}
```

Keep only:

```text
unit_type is one of 12 allowed values
confidence >= 0.75
statement length >= 8 characters
statement length <= 1200 characters
```

Manually inspect at least 100 examples before training.

### Suggested LLaMA-Factory Config

Create a training YAML similar to this:

```yaml
model_name_or_path: Qwen/Qwen3-1.7B
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
bf16: true
val_size: 0.1
logging_steps: 10
save_steps: 100
```

If your GPU does not support bf16, use:

```yaml
fp16: true
```

### Evaluation

Required metrics:

```text
Accuracy
Macro F1
Per-class precision
Per-class recall
Confusion matrix
Invalid output rate
```

Minimum pass line:

```text
Accuracy >= 0.85
Macro F1 >= 0.80
Invalid output rate = 0
```

If the model outputs anything other than one allowed label, count it as wrong.

## Phase 2: Train PKU JSON Extraction Model

### Purpose

This model extracts PKUs from a confirmed personal asset unit or document chunk.

Do not train relations in the first version. Keep `relations` as an empty list unless the teacher output is very clean.

### Training Input Example

```text
任务：从下面 Prism 个人资产单元中抽取 PKU。只输出严格 JSON。

标题：RAG 检索实验记录
摘要：测试 metadata filter 对检索质量的影响。
正文：只用向量检索时召回了很多同主题但不相关的内容，加 metadata filter 后结果明显更准。
```

### Training Output Example

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

### Data Requirements

Minimum:

```text
Asset-unit extraction examples: 500
Document chunk extraction examples: 0 for the first run
Validation: 10%
Test: 10%
```

Recommended first serious run:

```text
Asset-unit extraction examples: 1500-3000
Document chunk extraction examples: add later
Validation: 10%
Test: 10%
```

Why start with `personal_asset_unit`:

```text
It is shorter.
It is cleaner.
It already represents reviewed user knowledge.
It is less noisy than document chunks.
```

### Teacher Data Generation

For `PersonalAssetUnit`, use the existing prompt path:

```text
build_asset_unit_pku_extraction_messages
```

For `DocumentChunk`, use later:

```text
build_document_chunk_pku_extraction_messages
```

Keep only teacher outputs that pass:

```text
JSON parses successfully
pkus is a list
each pku has statement
each pku has unit_type in the 12 allowed values
each pku has evidence or evidence_span
confidence >= 0.70
evidence appears in the input text or is a close substring
```

Reject:

```text
Markdown-wrapped outputs
Unsupported unit_type
Empty PKU list
PKUs not supported by source text
Overly vague statements
Statements that are just titles
```

### Suggested LLaMA-Factory Config

For a 16 GB or 24 GB GPU:

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
bf16: true
val_size: 0.1
logging_steps: 10
save_steps: 100
```

If training runs out of memory:

```text
Set cutoff_len to 1024
Set lora_rank to 8
Set gradient_accumulation_steps to 16
Keep per_device_train_batch_size at 1
```

## Phase 3: Offline Evaluation

### Automatic Checks

Evaluate every output with deterministic checks:

```text
JSON valid rate >= 98%
pkus list exists
unit_type valid rate = 100%
statement non-empty rate = 100%
evidence non-empty rate >= 95%
evidence source-hit rate >= 85%
average PKU count is not obviously inflated
```

### Human Review

Randomly inspect 100 outputs.

Classify each output:

```text
A: Can be inserted into Prism directly
B: Needs small edits but is useful
C: Bad or unsafe
```

Pass line:

```text
A + B >= 80
C <= 20
```

If it fails:

```text
Do not connect the model to Prism
Clean the data
Add negative examples
Reduce task scope
Retrain
```

## Phase 4: Prism Replacement Strategy

Do not replace the main LLM directly.

Use this runtime policy:

```text
Try small model
  -> parse JSON
  -> validate schema
  -> validate unit_type
  -> validate evidence
  -> check confidence
  -> if all pass, use small model result
  -> otherwise call main LLM
```

First target:

```text
personal_asset_unit -> PKU extraction
```

Later target:

```text
document_chunk -> PKU extraction
```

Do not remove the existing main LLM path.

## Future Prism Integration Points

When offline evaluation passes, add a small-model path around these functions:

```text
backend/app/services/knowledge_governance.py

_extract_asset_unit_pkus_with_llm
_extract_document_chunk_pkus_with_llm
```

Future shape:

```python
small_result = _extract_asset_unit_pkus_with_small_model(unit)
if _small_model_result_is_safe(small_result, source_text=unit.content or unit.summary):
    return small_result
return _extract_asset_unit_pkus_with_llm(unit)
```

The validator should reject:

```text
Invalid JSON
No pkus
Unsupported unit_type
Missing statement
Missing evidence
Evidence not found in source
Confidence below threshold
Too many PKUs for a short input
```

Recommended first threshold:

```text
confidence >= 0.75
```

## Manual Execution Checklist

### Day 1: Label Design

- [ ] Write the 12-class label guide.
- [ ] Manually label 100 real Prism statements.
- [ ] Record confusing pairs.
- [ ] Adjust label definitions.

### Day 2: Build `unit_type` Dataset

- [ ] Export candidate statements from Prism.
- [ ] Ask main LLM to label them.
- [ ] Filter low-confidence labels.
- [ ] Manually inspect at least 100 examples.
- [ ] Create `train.jsonl`, `valid.jsonl`, and `test.jsonl`.

### Day 3: Train `unit_type`

- [ ] Install LLaMA-Factory.
- [ ] Download Qwen3-1.7B or Qwen3-4B-Instruct-2507.
- [ ] Run a 100-example smoke training job.
- [ ] Run full QLoRA training.
- [ ] Evaluate test set.
- [ ] Save confusion matrix.

### Day 4-5: Build PKU Extraction Dataset

- [ ] Generate teacher PKU JSON for confirmed asset units.
- [ ] Filter invalid teacher outputs.
- [ ] Remove markdown-wrapped or unsupported outputs.
- [ ] Manually inspect at least 100 examples.
- [ ] Create extraction train/valid/test JSONL files.

### Day 6: Train PKU Extraction

- [ ] Run 100-example smoke training.
- [ ] Confirm the model can output valid JSON.
- [ ] Run full QLoRA training.
- [ ] Evaluate JSON validity.
- [ ] Run human review.

### Day 7: Decide Whether To Integrate

- [ ] If metrics pass, design Prism small-model API wrapper.
- [ ] If metrics fail, improve data and retrain.
- [ ] Do not replace main LLM until offline metrics pass.

## Minimum Success Standard

The first successful milestone is:

```text
unit_type classifier:
  Accuracy >= 0.85
  Macro F1 >= 0.80
  Invalid output rate = 0

PKU extraction:
  JSON valid rate >= 98%
  unit_type valid rate = 100%
  evidence source-hit rate >= 85%
  human review A+B >= 80%
```

Only after this should Prism use the small model in the governance chain.

## References

- Qwen3 model family includes dense sizes such as 1.7B and 4B, and Qwen3 Instruct is designed for non-thinking instruction following.
- LLaMA-Factory supports Qwen3, SFT, LoRA, and 4-bit QLoRA workflows.
- QLoRA is designed to reduce memory usage by training adapters over a frozen 4-bit quantized base model.

