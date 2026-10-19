# 接入新平台 / 新 CRM

大多数平台**不需要写代码**：选一个通用适配器，配 `field_map` 即可。

## 1. 选接入方式
| 有什么 | type | 关键配置 |
|---|---|---|
| HTTP/JSON API | `api` | `url` `params` `headers`(用 `${ENV}`) `records_path` `pagination` `auth_fail_status` |
| 导出文件 CSV/XLSX/JSON/JSONL | `csv` | `path`（支持 `{date}` `{month}`）`max_age_minutes` `sheet` `encoding` |
| 只能看页面 | `browser-manual` | `capture_dir` `max_age_minutes`，按模板写 capture YAML |
| 平台推送 | `webhook` | `path`（receiver 写入的 JSONL） |
| 都不行 / 想直接用 SDK | `custom` | `class: my_pkg.mod:MyAdapter` |

## 2. 字段映射
`field_map` 把平台字段映射到规范字段（支持 `a.b.c` 取嵌套 JSON）：

| 规范字段 | 含义 | 必需 |
|---|---|---|
| `group` | 门店/人员名称（会按 groups + aliases 匹配） | ✅ |
| `time` | 客资时间（或用 `time_fields` + `date_attribution`） | ✅ |
| `kind` | 客资类型（phone/chat/form…），用于拆列；无则用 `default_kind` | |
| `contact` | 手机号/平台用户 ID（只哈希，不输出） | 去重/逐条匹配需要 |
| `count` | 平台只给汇总数时的数量 | |
| `channel` | CRM 渠道列 | CRM 必需 |
| 其它键 | 原样放进 `fields`（如响应时长的 `agent` `avg_seconds` `consults`） | |

## 3. 加一张报表
```yaml
reports:
  - id: fill_newplatform
    type: fill_gap
    source: newplatform
    crm_source: crm
    crm_channels: [新平台]        # CRM 渠道列的值
    group_by: stores
    columns: [{label: 客资数}]
schedules:
  morning: {reports: [..., fill_newplatform]}
```
`python run.py validate` 会检查引用是否存在。

## 4. 自定义来源适配器
```python
# my_adapters/acme.py
from adapters.base import SourceAdapter, AuthError

class AcmeLeads(SourceAdapter):
    def fetch(self, ctx):
        # 只读！用 ctx.data_day / ctx.period_start 决定拉取范围
        resp = my_sdk.list_leads(date=ctx.data_day.isoformat())
        if resp.status == 401:
            raise AuthError("acme: token expired")   # -> 告警，不当作 0
        rows = [{"store": x.shop, "created_at": x.ts, "phone": x.mobile} for x in resp.items]
        return self.result(rows, ctx)
```
```yaml
- {id: acme, type: custom, class: "my_adapters.acme:AcmeLeads", role: leads, group_by: stores,
   field_map: {group: store, time: created_at, contact: phone}}
```

## CRM 适配器
继承 `adapters.crm_base.CrmAdapter`，实现 `fetch_rows(ctx)`，返回覆盖 `[ctx.period_start, ctx.data_day]` 的记录（建议多取 1 天）。示意：

```python
from adapters.crm_base import CrmAdapter

class BitableCrm(CrmAdapter):          # 飞书/Lark 多维表格：records/search，按首次咨询时间过滤
    def fetch_rows(self, ctx): ...

class SalesforceCrm(CrmAdapter):       # SOQL: SELECT LeadSource, Store__c, FirstContact__c, Phone FROM Lead WHERE ...
    def fetch_rows(self, ctx): ...

class HubSpotCrm(CrmAdapter):          # CRM search API: contacts/deals 按 createdate / 自定义属性过滤
    def fetch_rows(self, ctx): ...
```
配置里用 `group_fields`（不同报表按不同列分组）、`time_fields`（first_contact / created / visit）、`field_map.channel` 指定列名。只读权限即可。

## 新的发送渠道
继承 `notifiers.base.Notifier`，实现 `send_text` 和 `send_image`（需要时覆盖 `send_file`），在 recipient 中用 `channel: {type: custom, class: "my_pkg.mod:MyNotifier", ...}`。密钥用 `*_env` 指向环境变量。
