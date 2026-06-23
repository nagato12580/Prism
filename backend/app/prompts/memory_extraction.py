from __future__ import annotations

from typing import Iterable

from backend.app.models.chat import ChatMessage


SYSTEM_PROMPT = """你是 Prism 的长期记忆抽取器。
只从对话中抽取对未来有帮助、可长期保存的用户记忆。

应该抽取：
- 用户明确偏好、长期目标、稳定约束
- 当前持续关注的项目或探索主题
- 已做出的产品/技术决策
- 对 agent 行为的长期要求

不要抽取：
- 临时命令、寒暄、一次性调试步骤
- 密码、token、密钥或敏感凭据
- 助手内部实现细节，除非它表达了用户认可的长期项目上下文
- 没有长期价值的普通问答内容

只输出严格 JSON，不要 Markdown，不要解释。
JSON schema:
{
  "candidates": [
    {
      "content": "一句完整、可独立理解的中文记忆",
      "statement_type": "preference|goal|constraint|decision|current_focus|project_context|interest|fact",
      "temporal_type": "stable|current|episodic",
      "confidence": 0.0,
      "importance": 0.0,
      "risk_level": "low|medium|high",
      "decision_hint": "review|auto_confirm_candidate|confirm_supersede",
      "evidence_message_id": "原始消息 id"
    }
  ]
}
"""


def build_memory_extraction_messages(messages: Iterable[ChatMessage]) -> list[dict[str, str]]:
    transcript_lines: list[str] = []
    for message in messages:
        content = (message.content or "").strip()
        if not content:
            continue
        transcript_lines.append(f"[message_id={message.id}] role={message.role}\n{content[:1600]}")
    transcript = "\n\n".join(transcript_lines) or "No conversation content."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"请从以下会话中抽取长期记忆候选：\n\n{transcript}",
        },
    ]
