# AI 助手 / Bot 的每日运行流程

适用于由 AI 助手（或值班同事）操作的部署：部分平台只能通过浏览器查看，需要“先取数、再运行”。

## 每个时段的步骤

1. **确定时段与数据日**：早报 = 昨天，晚报 = 今天（以 `config.timezone` 为准）。
2. **实时取数（每次都重新来）**，按来源类型：
   - `api` / `webhook` / `crm-sql`：无需操作，运行时自动拉取；
   - `csv` / `crm-csv`：登录平台/CRM 后台，按配置路径导出最新文件（文件修改时间必须在 `max_age_minutes` 内）；
   - `browser-manual`：打开平台后台对应页面，**只浏览、不操作**，读取各分组数字，写入 `captures/<source_id>/<数据日>.yaml`（模板 `examples/manual-capture.template.yaml`），`fetched_at` 填当前时间。
   - 不允许把上一个时段的导出、读数或截图当作本次数据。
3. **登录失效处理**：遇到登录页、二维码、验证码、会话过期 → 不要猜数、不要填 0：
   - `browser-manual` 来源把 capture 写成 `status: auth_failed` 并写明原因；API 来源返回 401/403 会被自动识别；
   - 运行后订阅 `alerts` 的接收人会收到“⚠️ 某平台取数失败 → 请扫码登录后重跑”，相关报表暂停；
   - 用户完成登录后，**重新取数并重跑该时段**，补发暂停的报表。
4. **运行**：`python run.py run --config config.yaml --slot <morning|evening>`
5. **核对 manifest**：`runs/<run_id>/manifest.json`
   - `sources.*.status` 全部 `ok`？`normalize.unmatched_group` 有没有未匹配的分组名（需要补 aliases）？
   - `mismatches[]` 中 `evidence_missing: true` 的条目：回到平台列表页，截图（遮挡手机号）放到 `evidence/<source_id>/`，在 capture 的 `evidence` 中登记，然后重跑，使证据随报表发出。
6. **发送**：
   - 有官方机器人 API 的渠道（飞书/企业微信/钉钉/Slack/Teams/Telegram/邮件/Webhook）由程序直接发送；
   - `wechat` / `agent_outbox`：读取 `runs/<run_id>/outbox/<recipient>.json`，用你自己的消息工具**按顺序发送其中的图片**（`send_as: image` 时不发文字说明，`caption` 只在有告警时出现），发完把 `status` 改为 `sent`。
   - 默认**只发图片**，不要把表格当文件发，除非该接收人 `format: file`。
7. **汇报**：向负责人简短说明本次是否全部发送、有哪些差额、哪些平台需要登录。

## 原则
- **只看不改**：不回复平台上的客户、不修改平台或 CRM 的任何数据、不点“导出给第三方/授权”等操作。
- **实时重拉**：每个时段都重新拉取；早报不能沿用前一晚的数字。
- **不编造**：取不到就是 “—” 或暂停，并告警。
- **按人发送**：只发给 `recipients` 里配置的对象，各自按自己的渠道、报表、格式、证据设置。
- **隐私**：截图遮挡手机号；不在聊天里粘贴密钥；运行目录不提交到 git。

## 调度
- `python run.py schedule --config config.yaml` 生成 crontab。
- 需要人工/助手取数的来源，可把 cron 时间设为“取数提醒”，助手完成取数后再执行 run。
- 退出码 `3` 表示有来源失败（已告警），可用于触发重试或通知。
