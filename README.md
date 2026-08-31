# 账单匣 LedgerBox

LedgerBox 是一个面向个人使用的微信 / 支付宝 / 招商银行账单归集工具。

现在整个流程都在一个项目里完成：

```text
iPhone 申请官方账单
        ↓
      专用邮箱
        ↓
LedgerBox 邮箱采集
        ↓
下载 / 解压 / 去重 / 解析
        ↓
内部转账识别 / 分类
        ↓
      SQLite
        ↓
  内置 Dashboard
```

支持：

- 微信 / 支付宝 / 招行官方账单
- CSV / XLSX
- IMAP 自动收取账单邮件
- Message-ID / IMAP UID 邮件去重
- SHA-256 附件去重
- 加密 ZIP 安全解压
- 缺少 ZIP 密码时进入 `waiting_password`，后台同步不会卡死
- 内部转账配对剔除
- 规则分类
- SQLite 持久化
- 月度 Markdown 报告
- 内置 Web Dashboard
- Dashboard 一键检查新账单
- Dashboard 输入 ZIP 密码并继续导入
- 月度汇总、分类支出、每日支出、流水分页、导入历史、待处理账单

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
cp config.example.yaml config.yaml
```

然后编辑 `config.yaml`，配置邮箱 IMAP 授权码。

> 邮箱请使用授权码 / 应用专用密码，不要填写邮箱登录密码。

## 推荐使用方式

### 1. iPhone 申请账单

当你想看阶段性总结时，在手机上分别申请：

**微信**  
我 → 服务 → 钱包 → 账单 → 下载账单 → 用于个人对账 → 填专用邮箱。

**支付宝**  
我的 → 账单 → 开具交易流水证明 → 用于个人对账 → 填专用邮箱。

**招商银行**  
手机银行 → 流水打印 / 收支明细 → 填同一邮箱。

### 2. 启动 Dashboard

```bash
python -m ledgerbox api
```

默认地址：

```text
http://127.0.0.1:8765/
```

打开以后可以直接：

- 查看当月支出 / 收入 / 净额 / 内部转移
- 查看分类支出和每日支出
- 浏览真实账本流水
- 查看最近导入邮件
- 查看等待密码或失败的账单
- 点击「检查新账单」执行一次完整邮箱同步
- 对 `waiting_password` 的 ZIP 直接输入密码并继续导入

不再需要额外的 React 前端项目，也不再使用浏览器 `localStorage` 保存账本。

## 一键同步

如果你只想通过 CLI：

```bash
python -m ledgerbox sync
```

执行：

```text
邮箱检查
  ↓
新邮件去重
  ↓
附件下载 / SHA-256 去重
  ↓
ZIP 解压
  ↓
解析
  ↓
内部转账匹配
  ↓
分类
  ↓
SQLite
  ↓
生成本月 Markdown 报告
```

重复运行是安全的。

## ZIP 密码

账单 ZIP 没有可用密码时不会阻塞同步，而会保存为：

```text
waiting_password
```

可以在 Dashboard 直接填写密码，也可以使用 CLI：

```bash
python -m ledgerbox status
python -m ledgerbox unlock a1b2c3d4e5f6
```

CLI 默认隐藏密码输入，避免密码进入 shell history。

## Dashboard / API 配置

默认：

```yaml
api:
  host: 127.0.0.1
  port: 8765
  token: ""
```

如果只在账本所在电脑访问，保持默认即可。

如果需要从 iPhone 或其他设备访问服务器上的 Dashboard，可以改为：

```yaml
api:
  host: 0.0.0.0
  port: 8765
  token: "请使用高强度随机值"
```

LedgerBox 对非 loopback 监听会强制要求 Token。

**不建议把 `http://服务器IP:8765` 直接裸露到公网。** 推荐放在 HTTPS 反向代理、VPN 或 Tailscale 后面。

当配置了 Token，Dashboard 的「访问设置」可在当前浏览器会话中填写。Token 仅存在 `sessionStorage`，关闭会话后不会作为账本数据持久化。

## HTTP 接口

只读：

```text
GET /health
GET /api/summary?month=2026-08
GET /api/transactions?month=2026-08&limit=50&offset=0
GET /api/imports?limit=50
GET /api/pending
```

操作：

```text
POST /api/sync
POST /api/unlock
```

`/api/unlock` 请求：

```json
{
  "sha256": "a1b2c3d4e5f6...",
  "password": "账单解压密码"
}
```

Web 写操作有单实例锁；如果另一个同步 / 解锁正在执行，会返回冲突状态，避免重复并发处理同一批附件。

API 不返回：

- IMAP 授权码
- ZIP 配置密码
- 附件本地绝对路径
- Dashboard 不需要的邮件发件人字段

## 内部转账规则

只有满足配对条件才记为「内部转移」：

- 对方命中 `transfers.keywords`
- 类型 / 描述含转账、充值、提现、转入、转出等
- 金额相同
- 时间差在配置窗口内，默认 48 小时
- 不同平台
- 收支方向相反

这样不会仅凭“支付宝”“微信”等单个关键词把普通消费误标成内部转账。

## 数据状态

SQLite 主要包含：

```text
transactions
mail_imports
attachments
```

`mail_imports` 保存邮件处理状态；`attachments` 保存附件 hash 和处理状态，因此程序重启后仍能知道哪些账单已经处理、哪些还在等密码。

## 其他命令

```bash
# 只拉新附件
python -m ledgerbox fetch

# 手动导入
python -m ledgerbox import
python -m ledgerbox import path/to/微信支付账单.xlsx

# 状态
python -m ledgerbox status

# 月报
python -m ledgerbox report
python -m ledgerbox report --month 2026-08
```

## 安全处理

相对原始账单采集思路，本项目额外处理了：

- SQL 参数化
- Zip Slip 路径校验
- 官方下载域名白名单
- 附件 / 解压 20MB 上限
- 密码不写日志
- `config.yaml`、`data/`、`inbox/` 不提交 Git
- 附件与邮件双层去重
- 非本机 Dashboard 强制 Token
- POST 操作串行化
- HTTP 响应不返回内部异常堆栈

仍建议只部署在自己可信的机器 / 服务器上。

## 致谢

- `edge-sky/Bills-save`：邮箱账单采集思路
- `aker-pc/BSync`：解析与归档流程参考

本仓库代码为重写实现。

## License

Mozilla Public License 2.0
