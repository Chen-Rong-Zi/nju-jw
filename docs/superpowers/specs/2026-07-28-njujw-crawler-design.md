# 南京大学教务处通知爬虫 — 设计文档

## 概述

对 `jw.nju.edu.cn/ggtz`（教务处通知公告）页面进行每日爬取，通过 API 获取通知数据，匹配用户关心的标签后发送邮件通知，并自动更新 README。

## 架构

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  API 主调用   │  →  │  详情页爬取   │  →  │  tag 匹配     │  →  │  邮件 / README│
│  HTML 兜底    │     │  内容摘要     │     │  (config.txt) │     │  更新        │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

## 数据流

1. **main.py** 每日通过 GitHub Actions 触发
2. 优先调用 API `/_wp3services/generalQuery?queryObj=articles` 获取通知列表
3. API 失败时回退到 HTML 解析（现有 `department.py` 逻辑）
4. 对比 `department.csv` 去重，识别新通知
5. 对新通知爬取详情页，提取正文前 50 字作为摘要
6. 匹配 `config.txt` 中用户关心的标签
7. 有匹配时生成 `email_content.html`（供 GitHub Action 发送邮件）
8. 更新 `README.md` 为最新通知表格
9. 追加新通知到 `department.csv`

## 组件

### 1. main.py — 主脚本

- **读取配置**：`config.txt`，每行一个 tag，精确匹配
- **API 调用**：POST `/_wp3services/generalQuery?queryObj=articles`
  - 参数：siteId=414, columnId=26263, pageIndex=1, rows=14
  - 返回字段：title, f1（标签, 多标签用"，"分隔）, publishTime, url
- **HTML 回退**：使用现有 `department.py` 的 lxml 解析逻辑
- **详情页爬取**：对每条新通知 URL 发起 GET 请求，提取正文前 50 字
- **标签匹配**：精确匹配，通知的标签列表包含任一用户 tag 即触发
- **输出**：
  - `email_content.html` — 邮件 HTML 内容（有匹配时生成）
  - `MATCHED=true` 环境变量标识（供 GitHub Actions 判断）
  - 更新 `README.md` 和 `department.csv`

### 2. config.txt — 用户配置

```
考试
毕业
课程
```

### 3. department.csv — 历史记录

格式：无表头，制表符分隔。用于去重。

```
tags\ttitle\ttime\turl
```

### 4. README.md — 每日更新

最新 10 条通知以 Markdown 表格展示，含摘要列。历史记录折叠在 `<details>` 中。

### 5. .github/workflows/daily.yml

- 定时触发：每天 UTC 1:00（北京时间 9:00）
- 支持 `workflow_dispatch` 手动触发
- 步骤：checkout → setup-python → pip install → run main.py → send email → commit
- 邮件通过 `dawidd6/action-send-mail` 发送
- 需要 GitHub Secrets：SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| API 请求失败 | 回退到 HTML 解析 |
| 详情页爬取失败 | 摘要显示"（无法获取内容）" |
| 无新通知 | 跳过邮件发送，仍更新 README |
| 无匹配 tag | 不发送邮件，仅更新 README 和 CSV |

## 依赖

- requests
- lxml
- Python 标准库：smtplib（仅用于邮件内容生成）、csv、json、re