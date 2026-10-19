# 首次配置问答脚本（AI 助手在“还没有 config.yaml”时照此提问）

与 `python run.py init` 的问题一一对应（括号里是 `--answers` 文件中的键）。一次问一组，不要一次抛出全部问题；用户没说的用默认值，并在最后复述确认。

## 第 1 组：业务与分组
1. 你的业务更像哪种？本地生活连锁门店 / 电商 / 教育培训 / 其他（`template`）
2. 时区？默认 Asia/Shanghai（`timezone`）
3. 按门店统计的话，有哪些门店？各门店在平台上还有别的叫法吗？（`stores`，别名之后写进 aliases）
4. 有没有按人统计的平台（例如社媒账号由不同员工负责）？有哪些人？（`people`）

## 第 2 组：CRM（对账的另一侧）
5. 客户记录存在哪里？飞书多维表格 / Salesforce / HubSpot / Excel / 数据库 / 其他（`crm_type`：能导出→crm-csv；数据库→crm-sql；要接 API→custom）
6. 导出文件放在哪 / 怎么拿到？（`crm_path`）
7. 这几列叫什么：渠道、门店、创建人、首次咨询时间、创建时间、到店时间、联系方式？（`crm_col_*`）

## 第 3 组：来源平台（逐个问）（`source_count`, `sources[]`）
对每个平台：
8. 平台叫什么？（`name`）
9. 数据怎么拿：有 API / 能导出表格 / 只能看页面 / 能推送？（`ingest`：api / csv / browser-manual / webhook）
10. 按门店还是按人统计？（`group_by`）
11. 平台上的客资要不要拆列？例如“电话数、后台咨询数”（`kinds`，写成 `phone:电话数,chat:后台咨询数`）
12. 这个平台的客资在 CRM 的“渠道”列里写的是什么？（`crm_channels`，必须一字不差）
13. （如有到店列）要不要做“核销/验券 vs 到店”对账？核销数据从哪个平台来？（`want_reconcile`, `verification_name`）

## 第 4 组：口径
14. 客资按“首次咨询日”还是“CRM 创建日”算哪天？（`date_attribution`，推荐首次咨询）
15. 每天从几点切日？（`day_start`，默认 00:00）
16. 同一个人一天咨询多次，算 1 条吗？（`dedupe`，默认 day）
17. CRM 哪些字段没填就不算“已填”？（`required_fields`）
18. 某个平台取不到数时：暂停相关报表并提醒，还是照发并显示 “—”？（`on_failure`，默认暂停）

## 第 5 组：时段
19. 早报几点？（复核昨天，默认 09:00；不要就留空）（`morning_time`）
20. 晚报几点？（统计今天，默认 21:00；不要就留空）（`evening_time`）

## 第 6 组：接收人（逐个问，必问）（`recipient_count`, `recipients[]`）
先问：**“报表要发给哪些人或哪些群？”** 列出名单后，对每一位：
21. 在哪个平台接收：飞书/Lark、企业微信、钉钉、微信、Slack、Teams、Telegram、邮件、通用 Webhook？（`channel`）
22. 私聊还是群？（`target_kind`）具体是谁/哪个群？（只记录称呼；ID/Webhook 放 .env，不要在聊天里贴密钥）
23. 收哪些：早报 / 晚报 / 登录失效提醒？（`reports`：morning, evening, alerts）
24. 格式：只发图片（默认，聊天里可直接预览）/ 图片+文字说明 / 文件附件？（`format`）
25. 数字对不上时，要不要附平台证据截图？（`evidence`）

最后：
26. 平台登录失效、需要扫码时，提醒谁、在哪个渠道？如果上面没人选“提醒”，必须指定一位。（`alert_recipient`）

## 收尾
- 复述：平台 × 接入方式 × 分组、CRM 列映射、口径、时段、每位接收人的 平台/对象/报表/格式/证据、告警接收人。用户确认后：
```bash
python run.py init --out config.yaml --answers answers.yaml
python run.py validate --config config.yaml
python run.py run --config config.yaml --slot morning --dry-run
```
- 把 dry-run 的图片发给用户核对口径（这是用户主动要求的预览，不是正式发送）。确认后再上线。
- 列出 `.env.example` 中需要用户自己填写的变量，告诉用户去哪个后台获取。
