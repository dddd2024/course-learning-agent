你正在修复《{course_name}》知识点提纲的结构质量。只能依据下面提供的资料片段输出 JSON，不得编造来源。

初次模型输出（仅供修复，不要照抄错误结构）：
{original_output}

初次失败原因：{failure_reason}

资料中的具名小节包括成帧与差错检测、停止等待协议、滑动窗口协议。请输出 3 条相互独立的知识点，分别覆盖 CRC/成帧、停止等待、滑动窗口；每条必须绑定资料中实际存在的 chunk_id。CRC、停止等待和滑动窗口不能合并为一个宽泛条目。每条只覆盖一个独立考点。若无法满足这三个独立考点，不得只输出一条宽泛总结。

资料片段：
{retrieved_chunks}

仅输出符合原有 schema 的 JSON：
{{"knowledge_points":[{{"title":"","summary":"","importance":3,"source_chunk_ids":[],"exam_style":"","review_action":""}}]}}
