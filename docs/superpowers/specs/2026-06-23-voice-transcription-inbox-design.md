# Prism 语音转写收件箱集成设计

## 目标

让用户通过语音录入想法和 idea，自动转写为文字后走现有资产收件箱 AI 解析 + 审核流程，最终沉淀到知识库。语音只是文本碎片的另一种输入模态。

## MVP 范围

- 收件箱顶部新增语音录入区域（实时录音 + 音频文件上传）
- 后端新增 `POST /api/v1/assets/voice` 端点
- 新增 `backend/app/services/asr.py` ASR 模块（DashScope Paraformer）
- 转写后文本无缝接入现有 `_create_asset_item_from_raw()` AI 解析管线
- 前端新增 `VoiceRecordButton` 组件
- `.env` 新增 ASR 配置项

暂不做：

- 移动端适配（桌面优先）
- 其他 ASR Provider（仅 DashScope）
- 语音内容自动向量化入库（仍走收件箱确认流程）
- 实时流式转写

## 数据流

```text
用户点击录音 / 拖拽音频文件
  → POST /api/v1/assets/voice (multipart audio)
  → 验证格式 + 大小
  → 保存音频到 backend/uploads/voice/{uuid}.{ext}
  → asr.transcribe(audio_path) → 转写文本
  → _create_asset_item_from_raw(db, raw_text=text, raw_source_type="voice", raw_metadata={...})
  → AI 解析 (分类/总结/标签/关系建议)
  → PersonalAssetItem (status=pending_review)
  → 返回 AssetDraft → 前端刷新收件箱列表
```

## API 设计

### `POST /api/v1/assets/voice`

**Request:** `multipart/form-data`
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `audio_file` | file | 是 | 音频文件，支持 mp3/wav/webm/m4a，≤ 25MB |
| `source_type` | string | 否 | `recording`（实时录音，默认）或 `upload`（文件上传） |

**Response:** `201 Created`
```json
{
  "id": 1,
  "title": "Prism 加语音转写功能",
  "summary": "用语音记录想法自动转文字进收件箱",
  "asset_kind": "idea",
  "tags": ["产品优化", "语音"],
  "status": "pending_review",
  "confidence": {"overall": 0.78},
  "raw_metadata": {"audio_path": "uploads/voice/xxx.webm", "duration_s": 23}
}
```

**错误码：**

| HTTP | code | 说明 |
|------|------|------|
| 400 | `unsupported_audio_format` | 不支持的音频格式 |
| 413 | `file_too_large` | 音频超过 25MB |
| 401 | `asr_key_invalid` | ASR API Key 无效 |
| 422 | `no_speech_detected` | 未检测到语音内容 |
| 500 | `asr_failed` | 语音识别服务失败 |
| 504 | `asr_timeout` | 语音识别超时（60s） |

## ASR 模块

**文件：** `backend/app/services/asr.py`

从 `ref/Comet/api/app/core/asr/transcriber.py` 移植并适配 Prism 配置系统。

```python
# 统一入口
async def transcribe(
    provider: str,       # "dashscope" (当前唯一)
    api_key: str,        # DashScope API Key
    model: str,          # "paraformer-v2"
    audio_path: str,     # 本地音频文件路径
) -> str:                # 转写文本
```

**DashScope 流程：**
1. 读取音频文件 → 上传到可公网访问的存储（或直接传 bytes 给 DashScope）
2. 提交录音文件识别任务 → 获取 task_id
3. 轮询任务状态（间隔 1.5s，最多 40 次 ≈ 60s）
4. 任务成功 → 下载 transcription_url 获取文本
5. 失败 / 超时 → 抛 BizError（中文提示）

> **注意：** DashScope Paraformer 要求音频 URL 可公网访问。如果本地开发环境无法提供公网 URL，需要先将音频上传到 OSS/MinIO 获取 URL，或使用 DashScope 的实时转写 API（WebSocket）。优先评估 Paraformer 实时转写 API 以避免额外的文件托管依赖。

## 前端组件

### VoiceRecordButton

**文件：** `frontend/src/components/VoiceRecordButton.tsx`

三种状态循环：

| 状态 | 外观 | 操作 |
|------|------|------|
| `idle` | 蓝色麦克风按钮 + "语音录入" 标签 + 拖拽区 | 点击开始录音 / 拖拽文件 |
| `recording` | 红色脉冲动画 + 计时器 + 停止按钮 | 点击停止 / 60s 自动停止 |
| `processing` | 蓝色旋转加载 + 进度文字（转写中 → AI 解析中） | 不可操作，等待完成 |

**Props:**
```typescript
interface Props {
  onResult: (item: AssetDraft) => void  // 转写+解析完成后回调
}
```

**技术细节：**
- 录音：`navigator.mediaDevices.getUserMedia({ audio: true })` + `MediaRecorder`
- 编码：`audio/webm` (Chrome/Edge 默认)
- 上传：`FormData` + `assetApi.createVoice()`
- 文件上传：`<input type="file" accept="audio/*">` + 拖拽事件
- 最长录音：60 秒，到时自动停止

### InboxPage 改动

在"添加碎片"面板上方嵌入 `VoiceRecordButton`，`onResult` 回调触发列表刷新。

## 配置

`.env` 新增：

```bash
# ASR 语音识别
ASR_PROVIDER=dashscope
ASR_API_KEY=sk-xxxxxxxx
ASR_MODEL=paraformer-v2
```

`backend/app/config.py` 新增：

```python
ASR_PROVIDER: str = "dashscope"
ASR_API_KEY: str = ""
ASR_MODEL: str = "paraformer-v2"
```

## 改动清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `backend/app/services/asr.py` | 新建 | DashScope ASR 模块，从 ref/Comet 移植 |
| 2 | `backend/app/api/assets.py` | 修改 | 新增 `POST /assets/voice` 端点 + `_voice_to_asset_item()` |
| 3 | `backend/app/config.py` | 修改 | 新增 3 个 ASR 配置项 |
| 4 | `frontend/src/components/VoiceRecordButton.tsx` | 新建 | 录音 + 上传组件 |
| 5 | `frontend/src/pages/InboxPage.tsx` | 修改 | 顶部嵌入 VoiceRecordButton |
| 6 | `frontend/src/app/api.ts` | 修改 | 新增 `assetApi.createVoice()` |
| 7 | `.env` / `.env.prod.example` | 修改 | 新增 ASR 配置 |

**不改动：**
- 数据库表结构（`PersonalAssetItem` 字段足够）
- AI 解析管线（`_ai_parse_asset` / `_create_asset_item_from_raw`）
- 收件箱审核 / 确认 / 拒绝流程
- 知识库向量化流程

## 测试策略

### 单元测试
- `backend/tests/test_asr.py`：mock httpx 测试 DashScope 转写各分支（成功/失败/超时/空文本）

### 集成测试
- `backend/tests/test_asset_voice.py`：测试 `POST /assets/voice` 端点完整流程（mock ASR）

### 前端
- VoiceRecordButton 组件渲染测试
- 与现有 E2E 测试保持一致即可

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| DashScope 需要公网 URL 访问音频 | 评估实时转写 API（WebSocket）或先用 MinIO 做临时上传 |
| 中文转写准确度不够 | 收件箱审核环节允许用户编辑修正文本 |
| 录音体验受浏览器限制（需 HTTPS/localhost） | 降级方案支持直接上传音频文件 |
| 同步转写 + AI 解析耗时较长（~5-10s） | 前端 loading 动画给足反馈；后续可改为异步 |
