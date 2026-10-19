# 从零开始（快速上手）

整个过程只需要“配置你自己的平台和 CRM”，不用改代码。

## 0. 准备

- Python 3.10+；中文字体（Linux：`sudo apt install fonts-noto-cjk`；macOS 自带 PingFang SC；Windows 自带 Microsoft YaHei）。
- 你要对账的平台后台账号（只需要**查看**权限）、CRM 的导出或只读接口。

```bash
git clone <repo> && cd lead-report-workflow
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                     # 读 xlsx 再加：pip install openpyxl
```

## 1. 先跑示例

```bash
python run.py demo
```
生成假数据并出早报、晚报两套图到 `examples/runs/<run_id>/`，`outbox/` 里是“本来会发给谁、发哪几张”。打开看看是不是你要的样子。

## 2. 选来源平台

列出你每天接客资的平台，对每个平台决定**接入方式**（见 README 平台覆盖表）：

| 平台情况 | 用 | 你要准备 |
|---|---|---|
| 有开放 API | `api` | API 地址、token（放环境变量） |
| 后台能导出表格 | `csv` | 每次运行前导出到 `exports/`（或让 AI 助手导出） |
| 只能看页面 | `browser-manual` | 每次运行前读数写 `captures/<id>/<日期>.yaml`（模板 `examples/manual-capture.template.yaml`） |
| 能推送到你的地址 | `webhook` | 部署 `python -m adapters.webhook_inbox` |

同时决定每个平台**按什么分组**：门店（stores）还是人员（people）。

## 3. 连接 CRM

CRM 必须能给出这些列：**渠道**（每条客资来自哪个平台）、**门店/负责人**、**首次咨询时间**；可选：联系方式、到店时间。

- 任何 CRM 都能导出 → `crm-csv`（最简单）
- 有只读数据库视图 → `crm-sql`
- 想直接调 API（多维表格 / Salesforce / HubSpot…）→ 写一个 `custom` 适配器（[platforms.md](platforms.md#crm-适配器)）

⚠️ 渠道取值要和配置里的 `crm_channels` **完全一致**（精确匹配，“平台A”不会匹配“平台A二店”）。

## 4. 定义口径

见 [metric-rules.md](metric-rules.md)。最少要确定：
1. 客资按哪天算：**首次咨询日**（推荐）还是 CRM 创建日；
2. 几点切日（默认 00:00）；
3. 同一个人一天咨询多次算几条（默认 1 条）；
4. 哪些不算有效客资（测试、广告、骚扰…）；
5. CRM 哪些字段必填，缺了就不算“已填”。

## 5. 生成配置

```bash
python run.py init                 # 终端问答；或从模板起步：cp config/templates/local-life-chain.yaml config.yaml
```
向导会依次问：模板 → 时区 → 门店/人员 → CRM → 各来源平台 → 口径 → 早晚时段 → **每位接收人**（平台、私聊/群、收哪些报表、只发图/图+文字/文件、是否附证据截图）→ 登录失效提醒谁。
生成 `config.yaml` 和 `.env.example`。

## 6. 设置发送渠道

把 `.env.example` 另存为 `.env`，填入各渠道的密钥/目标 ID（不要提交到 git）：

| 渠道 | 需要 |
|---|---|
| 飞书 / Lark | 自建应用 App ID / Secret（开通发消息、上传图片权限），接收人 open_id 或群 chat_id |
| 企业微信群机器人 | 群机器人 Webhook |
| 钉钉群机器人 | Webhook + 图片托管地址 `image_base_url`（钉钉机器人不能直接传图） |
| 微信（个人） | 无官方机器人：写入 outbox，由 AI 助手或人工代发 |
| Slack | Bot token（files:write, chat:write）+ channel ID |
| Teams | Workflows/Incoming Webhook + `image_base_url` |
| Telegram | Bot token + chat id |
| Email | SMTP 主机/端口/账号/密码 + 收件人 |
| 通用 Webhook | URL（+ 可选 token），multipart 上传图片 |

```bash
set -a; . ./.env; set +a
python run.py validate --config config.yaml --check-env
```

## 7. 试跑

```bash
python run.py run --config config.yaml --slot morning --dry-run
```
检查 `runs/<run_id>/`：图片、`manifest.json`（每个来源状态、每张表的数、差额与证据）、`outbox/`（每个接收人会收到什么）。**对着平台后台人工核一遍数**，确认口径一致。

## 8. 上线

```bash
python run.py schedule --config config.yaml   # 输出 crontab，粘贴到 crontab -e
```
- 全部是 `api`/`webhook`/`crm-sql` 来源：直接 cron 或 CI 定时跑。
- 有 `csv`/`browser-manual` 来源：交给 AI 助手按 [SKILL.md](../SKILL.md) 每天先取数再运行，或安排人员在时段前导出/读数。
- 退出码：`0` 正常；`3` 有来源失败（已告警）；`1/2` 配置问题。
