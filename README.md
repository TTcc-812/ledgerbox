# 账单匣 LedgerBox

基于 [aker-pc/BSync](https://github.com/aker-pc/BSync) 与 [edge-sky/Bills-save](https://github.com/edge-sky/Bills-save) 的邮箱账单流程，**重写并加固**后的个人账本。

支持 **微信 / 支付宝 / 招商银行** 官方导出文件（邮箱附件或本地导入），自动：

- 解析 CSV / XLSX
- 识别内部转账（卡 ↔ 微信 ↔ 支付宝 不计收入/支出）
- 写入本地 SQLite
- 生成月度 Markdown 报告

数据只落在你自己的电脑上。邮箱密码用授权码，不要用登录密码。

## 安全说明（相对原项目修了什么）

原 BSync 存在这些问题，本仓库已避开：

| 问题 | 原项目 | 本仓库 |
| --- | --- | --- |
| SQL 拼接账单字段 | `INSERT ... VALUES ('{}')` | 参数化查询 |
| Zip Slip | `extract` 不校验路径 | 拒绝 `..` / 绝对路径 |
| 任意 URL 下载 | 从邮件 HTML 取链接直接 GET | 仅允许微信/支付宝/招行官方域名 |
| 解压密码写进日志 | debug 打印密码 | 不记录密码 |
| 配置里的密钥被提交 | 示例路径写死本机 | `config.yaml` 已 gitignore，只用 example |
| 无体积限制 | 无 | 附件与解压上限 20MB |

请仍只在本机运行，不要把 `config.yaml`、`data/` 推到公开仓库。

## 流程

1. 手机把微信 / 支付宝 / 招行流水发到**专用邮箱**（用于个人对账）。
2. 电脑运行 `python -m ledgerbox fetch` 拉取附件并解压，或把已下载文件放到 `inbox/`。
3. `python -m ledgerbox import` 解析、去重、标记转账。
4. `python -m ledgerbox report` 看这个月钱花在哪。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp config.example.yaml config.yaml
# 编辑 config.yaml：邮箱 IMAP 授权码、解压密码（可留空，运行时输入）
```

## 命令

```bash
# 从邮箱拉取最近账单（需在 config.yaml 填 IMAP）
python -m ledgerbox fetch

# 导入 inbox/ 或指定文件
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

- 对方含：支付宝、微信支付、微信零钱、余额宝、招商银行、招行、储蓄卡 等
- 类型含：转账、充值、提现、转入、转出
- 金额相同、时间差在配置的窗口内（默认 48 小时）的配对流水会互相抵消

可在 `config.yaml` 的 `transfers.keywords` 自行增删。

## 致谢

- [edge-sky/Bills-save](https://github.com/edge-sky/Bills-save)（MPL-2.0）邮箱拉取思路
- [aker-pc/BSync](https://github.com/aker-pc/BSync) 解析与归档流程

本仓库代码为重写，不以复制原文件的方式分发。

## 许可

Mozilla Public License 2.0（与 Bills-save 兼容）
