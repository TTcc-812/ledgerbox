# 账单匣 LedgerBox

基于 [aker-pc/BSync](https://github.com/aker-pc/BSync) 与 [edge-sky/Bills-save](https://github.com/edge-sky/Bills-save) 的邮箱账单流程，**重写并加固**后的个人账本。

支持 **微信 / 支付宝 / 招商银行** 官方导出文件（邮箱附件或本地导入），自动：

- 解析 CSV / XLSX
- 识别内部转账（卡 ↔ 微信 ↔ 支付宝 不计收入/支出）
- 写入本地 SQLite
- 生成月度 Markdown 报告
- 按邮件 Message-ID / IMAP UID 与附件 SHA-256 去重
- 加密账单缺少密码时进入 `waiting_password`，不会阻塞后台同步

数据只落在你自己的电脑或服务器上。邮箱密码用授权码，不要用登录密码。

## 安全说明（相对原项目修了什么）

原 BSync 存在这些问题，本仓库已避开：

| 问题 | 原项目 | 本仓库 |
| --- | --- | --- |
| SQL 拼接账单字段 | `INSERT ... VALUES ('{}')` | 参数化查询 |
| Zip Slip | `extract` 不校验路径 | 拒绝 `..` / 绝对路径 |
| 任意 URL 下载 | 从邮件 HTML 取链接直接 GET | 仅允许微信/支付宝/招行官方域名 |
| 解压密码写进日志 | debug 打印密码 | 不记录密码；`unlock` 默认隐藏输入 |
| 配置里的密钥被提交 | 示例路径写死本机 | `config.yaml` 已 gitignore，只用 example |
| 无体积限制 | 无 | 附件与解压上限 20MB |
| 重复拉取/重复附件 | 无状态 | Message-ID / UID + SHA-256 双层去重 |

请仍只在可信环境运行，不要把 `config.yaml`、`data/`、`inbox/` 推到公开仓库。

## 推荐流程

1. 手机把微信 / 支付宝 / 招行流水发到**专用邮箱**（用于个人对账）。
2. 服务器或电脑运行 `python -m ledgerbox sync`。
3. LedgerBox 自动拉邮件、下载附件、解压可处理账单、解析、去重、标记内部转账、分类并生成本月报告。
4. 如果某个 ZIP 需要临时密码，任务不会卡住；运行 `python -m ledgerbox status` 查看待处理附件，再用 `unlock` 补密码。

### 一键同步

```bash
python -m ledgerbox sync
```

适合后续放进 systemd timer / cron。重复运行是安全的：已处理邮件和相同附件会跳过，交易仍由交易 ID 做最终去重。

### 查看待处理状态

```bash
python -m ledgerbox status
```

示例：

```text
待处理附件：
- a1b2c3d4e5f6  waiting_password  微信支付账单.zip  等待解压密码
```

### 补 ZIP 密码并继续导入

```bash
python -m ledgerbox unlock a1b2c3d4e5f6
```

密码会以隐藏方式输入，不进入 shell history。也支持第二个参数直接传密码，但不推荐在长期使用的机器上这么做。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp config.example.yaml config.yaml
# 编辑 config.yaml：邮箱 IMAP 授权码；固定解压密码可填，临时密码建议留空
```

## 其他命令

```bash
# 只从邮箱拉取新附件，不导入
python -m ledgerbox fetch

# 手动导入 inbox/ 或指定文件
python -m ledgerbox import
python -m ledgerbox import path/to/微信支付账单.xlsx

# 月报
python -m ledgerbox report
python -m ledgerbox report --month 2026-08
```

## 导出路径（发到同一邮箱）

**微信**  
我 → 服务 → 钱包 → 账单 → 下载账单 → **用于个人对账** → 填邮箱。解压密码在微信支付服务通知。

**支付宝**  
我的 → 账单 → 开具交易流水证明 → **用于个人对账** → 填邮箱。

**招商银行**  
手机银行 → 流水打印 / 收支明细 → 填邮箱。提取码在申请记录。

## 内部转账规则

同时满足则记为「内部转移」，不计入净收支：

- 对方命中 `config.yaml` 的 `transfers.keywords`（未配置时使用内置平台关键词）
- 类型/描述包含：转账、充值、提现、转入、转出
- 金额相同、时间差在配置的窗口内（默认 48 小时）
- 必须是不同平台、收支方向相反的一对流水

这样不会只凭“支付宝/微信”等单个关键词就把普通付款误标成内部转移。

## 数据库状态

除 `transactions` 外，SQLite 现在还记录：

- `mail_imports`：邮件 Message-ID、IMAP UID、主题、处理状态、错误信息
- `attachments`：附件 SHA-256、文件名、平台、处理状态、错误信息

这些状态用于无人值守同步、重复执行和后续 Web 管理页面。

## 致谢

- [edge-sky/Bills-save](https://github.com/edge-sky/Bills-save)（MPL-2.0）邮箱拉取思路
- [aker-pc/BSync](https://github.com/aker-pc/BSync) 解析与归档流程

本仓库代码为重写，不以复制原文件的方式分发。

## 许可

Mozilla Public License 2.0（与 Bills-save 兼容）
