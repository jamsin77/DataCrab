---
name: training-video-knowledge-extraction
description: 对培训/教学视频抽帧、OCR识别、语义提取，形成结构化培训知识并入库
version: "1.0.0"
tags:
  - 视频处理
  - 知识提取
  - OCR
  - 培训
  - 语义分析
---

# 培训视频知识提取

## 功能说明
对培训/教学视频进行自动化知识提取，完整流程如下：

1. **视频元数据提取** — 获取时长、分辨率、帧率、编码等信息
2. **关键帧抽取** — 基于场景检测自动抽取视频关键画面（可配置帧数）
3. **帧内容分析（并发）** — 对每个关键帧调用大模型视觉能力，提取文字内容、画面描述、知识点主题
4. **语义聚合提取** — 将所有帧分析结果送入大模型进行语义聚合，去重整合为结构化知识条目
5. **知识入库** — 将提取的知识点写入指定数据源表，支持分批写入

## 使用方式
```
从视频 "/data/videos/safety_training.mp4" 提取培训知识，写入 "凭证检索库" 的 "training_knowledge" 表
```
```
处理视频 "/data/videos/equipment_operation.mp4"，抽取 12 帧，结果写入 "凭证检索库" 的 "training_knowledge" 表
```

## 参数规范

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `video_path` | str | ✅ | - | 视频文件路径（须在授权目录内） |
| `datasource_name` | str | ❌ | 凭证检索库 | 输出数据源名称 |
| `table_name` | str | ❌ | training_knowledge | 输出表名 |
| `max_frames` | int | ❌ | 8 | 最大抽取帧数 |
| `if_table_exists` | str | ❌ | replace | 写入策略：fail/append/replace/overwrite/truncate |
| `max_workers` | int | ❌ | 4 | 帧分析并发数 |

## 输出表结构

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | str | 记录唯一ID |
| `video_name` | str | 视频文件名 |
| `video_path` | str | 视频完整路径 |
| `video_duration` | float | 视频时长（秒） |
| `video_resolution` | str | 视频分辨率 |
| `frame_count` | int | 抽取帧数 |
| `knowledge_point` | str | 知识点标题 |
| `category` | str | 知识分类 |
| `content` | str | 知识详细内容 |
| `importance` | str | 重要程度（高/中/低） |
| `chapter` | str | 所属章节 |
| `timestamp_ref` | str | 对应视频时间戳 |
| `extracted_at` | str | 提取时间 |

## 脚本说明

| 脚本 | 说明 |
|------|------|
| `main.py` | 核心处理脚本：视频抽帧→帧分析→语义提取→知识入库 |