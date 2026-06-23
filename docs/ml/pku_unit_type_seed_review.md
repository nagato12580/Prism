# PKU unit_type 种子训练数据核对表

这批数据用于 smoke test 和人工核对，不是最终训练集。

文件：

```text
docs/ml/pku_unit_type_seed.jsonl
```

数据规模：

```text
总样本数：96
类别数：12
每类样本数：8
```

标签集合：

```text
concept
definition
claim
method
rule
observation
experiment_result
decision
problem
question
pattern
constraint
```

## 使用建议

第一步先人工核对，不要直接训练。

重点看这些混淆边界：

```text
claim vs observation
observation vs experiment_result
problem vs question
method vs rule
pattern vs method
concept vs definition
```

如果你不同意某条标签，直接改 `pku_unit_type_seed.jsonl` 里对应 assistant 的 `content`。

## 这批数据的定位

它适合：

- 验证 LLaMA-Factory 数据格式；
- 训练一个极小 smoke test；
- 检查模型能否输出 12 类之一；
- 帮你感受不同 unit_type 的边界。

它不适合：

- 作为正式训练集；
- 评估真实泛化效果；
- 直接替换 Prism 线上链路。

正式训练至少需要：

```text
总样本数：1200 起步
每类：至少 50 条
推荐总样本数：3000+
推荐每类：100+
```

## LLaMA-Factory 数据集配置提示

如果使用 ShareGPT 格式，可以在 LLaMA-Factory 的 `dataset_info.json` 中增加类似配置：

```json
{
  "prism_pku_unit_type_seed": {
    "file_name": "pku_unit_type_seed.jsonl",
    "formatting": "sharegpt",
    "columns": {
      "messages": "messages"
    }
  }
}
```

具体路径取决于你把数据放到 LLaMA-Factory 的哪个 `data` 目录。

## 3090 smoke test 建议参数

```yaml
model_name_or_path: Qwen/Qwen3-4B-Instruct-2507
stage: sft
do_train: true
finetuning_type: lora
template: qwen
dataset: prism_pku_unit_type_seed
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
logging_steps: 5
save_steps: 20
```

