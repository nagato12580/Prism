from __future__ import annotations

from backend.app.models.chat import ChatMessage


SYSTEM_PROMPT = """你是 Prism 的长期记忆抽取器。
从对话中抽取对未来有帮助、可长期保存的用户记忆。

输入包含三个部分：
1. [会话背景] — 整个对话的摘要，帮助你理解大语境
2. [上文语境] — 最近已提取过的历史消息，**仅供理解语境，不要从中提取记忆**
3. [待提取消息] — 需要抽取的新消息，**只从这里产出记忆候选**

应该抽取：
- 用户明确偏好、长期目标、稳定约束
- 当前持续关注的项目或探索主题
- 已做出的产品/技术决策
- 对 agent 行为的长期要求
- 被重复提及的主题或工具选择

不要抽取：
- 临时命令、寒暄、一次性调试步骤
- 密码、token、密钥或敏感凭据
- 助手内部实现细节，除非它表达了用户认可的长期项目上下文
- 没有长期价值的普通问答内容
- 纯技术错误堆栈

对每条候选，给出以下信号：
- confidence: 0-1, 你对提取正确性的信心
- explicitness: 0-1, 用户是否明确说出（1.0=直接陈述，0.5=可推断，0.2=高度推测）
- sensitivity_flag: true/false, 是否涉及身份、健康、财务、密码等敏感个人信息

只输出严格 JSON，不要 Markdown，不要解释。
JSON schema:
{
  "session_summary": "一句话中文概括本对话主题和已达成结论",
  "candidates": [
    {
      "content": "一句完整、可独立理解的中文记忆",
      "statement_type": "fact|preference|goal|constraint|decision|project_context|topic_interest|question",
      "temporal_type": "stable|current|episodic",
      "confidence": 0.0,
      "importance": 0.0,
      "explicitness": 0.0,
      "sensitivity_flag": false,
      "evidence_message_id": "原始消息 id"
    }
  ]
}
"""


def build_memory_extraction_messages(
    new_messages: list[ChatMessage],
    context_messages: list[ChatMessage] | None = None,
    session_summary: str = "",
) -> list[dict[str, str]]:
    """构建提取 prompt，含会话摘要、上下文窗口和待提取消息。"""

    def _format_messages(messages: list[ChatMessage], label: str) -> str:
        if not messages:
            return f"[{label}]\n(无消息)"
        lines: list[str] = [f"[{label}]"]
        for m in messages:
            content = (m.content or "").strip()
            if not content:
                continue
            lines.append(f"[message_id={m.id}] role={m.role}\n{content[:1600]}")
        return "\n\n".join(lines)

    context_block = _format_messages(context_messages or [], "上文语境 — 仅供理解，不从中提取")
    target_block = _format_messages(new_messages, "待提取消息 — 只从这里提取记忆")

    summary_text = session_summary or "(新会话，无已有摘要)"

    user_prompt = (
        f"[会话背景]\n{summary_text}\n\n"
        f"{context_block}\n\n"
        f"{target_block}"
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
