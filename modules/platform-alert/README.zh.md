# platform-alert · 通用平台预警

任意平台 × 任意指标的每日预警：余额/可用天数、花费、客资、客服响应时长、评分、差评、库存……或页面上任意一个数。
每天（人或 AI 助手只读）读数 → `evaluate.py` 按规则判定 → 渲染话术 → 按接收人各自的平台发送。

## 1. 询问式配置向导（核心）

```bash
python modules/platform-alert/wizard.py --out platform-alert.yaml            # 终端逐项问
python modules/platform-alert/wizard.py --answers answers.yaml --out platform-alert.yaml   # AI 助手在聊天里问完后批量写入
```
也可在 `python run.py init` 最后回答「是否开启通用平台预警」，会沿用已配置的接收人。

向导**一次只问一个问题**，答错当场重问；选项可填序号、英文键或中文（如「企微」「2」「wecom」）。
**1 个接收人 + 1 个平台 + 1 个指标 = 12 问，约 2 分钟**（旧版 26 问）。流程：

1. 触发后通知谁？一行写「称呼 + 渠道（+ 群）」，如 `财务负责人 飞书`、`运营群 企微 群`、`ops@shop.com`、`#inventory slack`
   （渠道：feishu / wecom / dingtalk / wechat / slack / email）
2. 再加一个接收人吗？（y/n）
3. 监控哪个平台
4. 用哪个账号登录（只写别名，不写密码）
5. 盯哪个数：填序号（余额/花费/客资/响应时长/评分/差评/库存）或直接写名字（自定义）
6. 这个数在后台哪个页面/字段
7. 什么情况下提醒：`below` 低于、`above` 高于、`days_left` 值÷近7天日均、`change_pct` 较上期变化%、`zero_or_missing` 为0或读不到
8. 阈值（change_pct：30 = 下降超过 30%，-30 = 上涨超过 30%）
9. 提醒话术（回车用默认）
10. 还要再加吗？（完成 / 同平台再盯一个数 / 加一个新平台）
11. 每天几点检查（`09:30` / `9:00,18:00` / `工作日 10:00` / `每周一 9:30` / cron）
12. 要改高级设置吗？（默认跳过）：时区、后台网址、登录步骤、子账户切换步骤、没触发也发、正常话术

有多个接收人时，会多问「这个数通知谁」「登录失效提醒谁」（回车=全部/第一个）；只有一个接收人时自动跳过。
问完打印中文摘要供核对。默认话术不带货币和行业用语，格式统一为 `【平台·指标】…`。

## 2. 每天运行

读数写成 JSON（平台名 → 指标 → value / history / prior / daily_budget；读不到登录就写 `"login_ok": false`）：
```bash
python modules/platform-alert/evaluate.py platform-alert.yaml readings.json   # 只计算不发送
# 退出码：0 正常 / 2 有触发 / 3 读不到数、登录失效或平台名拼错
```
输出 `messages`：接收人 → 要发的文本（可接仓库 `notifiers/`）。
规则要点：读不到的数（或 change_pct 缺上期值）**绝不当 0、也不会当成“正常”**，而是以「今天没读到（页面位置），请人工确认」发给 `login_expired_recipients`，不会用业务话术发出「余额¥—」之类的怪消息；读数里的平台名和配置对不上会单独报出；`days_left` 还会在 `值 < 阈值×日预算` 时触发（防止近期没花、一开投当天花完）。

话术变量：`{platform} {metric} {value} {threshold} {days} {pct}`。

## 3. 示例：广告账户余额预警

`examples/ad-balance.yaml` + `examples/ad-balance.readings.json`，输出形如：
```
小红书当前余额¥700，预计1天内耗尽，请尽快充值。
大众点评余额¥20,000，可用约8天，暂不需充值。
```

## 平台小贴士（通用经验）

- **大众点评推广通**：首页余额可能显示 0，真实可用余额在 **推广财务 → 综合推广余额**。
- **小红书聚光**：品牌号下可能显示花费 0，实际投放在代理商子账户；点 **右上角品牌账户 → 切换**，选实际投放的子账户。
- 登录失效/扫码过期时不出数，只提醒 `login_expired_recipients` 去登录。
- 只看不改：不充值、不改预算、不回复客户。

## 隐私

不要把账号 ID、人员姓名、手机号、真实金额、公司名写进仓库；接收人 ID 用 `target_env` 环境变量。
