# 密钥与 Git 账号配置指南

> 原则：**不要把 API Key、PAT、密码或私钥发到聊天里**，也不要把它们写进
> 受版本控制的文件。聊天记录、命令历史与日志都可能留存明文。

## 1. 你可以安全地告诉我什么

| 信息 | 是否可以发我 | 说明 |
| --- | --- | --- |
| 使用哪家模型、哪个模型名 | ✅ | 例如 DeepSeek `deepseek-flash` |
| "Key 已写入 `.env`" | ✅ | 我只需要知道可以去重启/验证 |
| Git 的 `user.name` / `user.email` | ✅（如不介意） | 这是提交身份，不是密码 |
| 仓库平台、组织/用户名、remote URL | ✅ | 非敏感公开信息 |
| SSH **公钥**（`.pub`） | ✅ | 用于添加到 GitHub/Gitee |
| **API Key / PAT / 密码 / 私钥** | ❌ | 不要粘贴到聊天、Issue、README |

## 2. API Key：写入本地 `.env`

所有本地环境变量文件都已被 [`.gitignore`](../.gitignore) 忽略：

```
ai-engine-py/.env        # LLM / Embedding / Rerank Key
gateway-go/.env          # 数据库、Redis、内部 Token
deploy/.env              # 本地 PostgreSQL/Redis 凭据
frontend/.env.local      # 前端 API 地址
```

操作步骤：

```powershell
# 1) 打开本地文件（不会提交）
notepad .\ai-engine-py\.env

# 2) 按能力分别填写，例如：
# LLM_BASE_URL=https://api.deepseek.com
# LLM_API_KEY=sk-...
# CHAT_MODEL=deepseek-flash
# EMBEDDING_API_KEY=sk-...        # Embedding 需另一家或本地模型
# RERANK_API_KEY=...              # 可选

# 3) 重启
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\stop-all.ps1
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\start-all.ps1
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\status.ps1
```

完成后只需告诉我："Key 已写入 `.env`，可以重启验证"。我不会读取或打印 Key 值；
健康探针只判断"是否配置"，不会把 Key 写进响应或日志。

> 注意：当前 `/health` 只检查 Key 是否存在，不验证 Key 是否有效。真实调用是否
> 成功要等 Phase 2 的模型客户端，或后续增加一个不输出密钥的 Provider 连通性测试。

如果 Key 不小心发到了聊天/公开位置：

1. 立即到供应商控制台吊销并重新生成；
2. 更新本地 `.env`；
3. 不需要把新 Key 发给我。

生产环境不要用 `.env`：使用阿里云 KMS / SAE 环境变量 / 密钥管理服务。

## 3. Git 身份（非敏感）

当前目录还不是 Git 仓库，且尚未配置全局身份。可以自己执行，或把
`user.name` / `user.email` 告诉我：

```powershell
git config --global user.name "你的名字"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
```

如果担心隐私，可使用 GitHub 提供的 noreply 邮箱。

## 4. Git 认证（密码/Token/私钥，不要发我）

### 方案 A：SSH（当前环境可用，推荐）

Windows 自带 OpenSSH（`C:\Windows\System32\OpenSSH\ssh.exe`），MinGit 也带 SSH。

```powershell
ssh-keygen -t ed25519 -C "you@example.com"
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

把输出的**公钥**添加到 GitHub/Gitee/GitLab。然后配置 SSH remote：

```powershell
git remote add origin git@github.com:<user>/<repo>.git
ssh -T git@github.com
```

**私钥 `id_ed25519` 永远不要发给我或提交到仓库。**

### 方案 B：HTTPS + Credential Manager

HTTPS 首次 push 时由 Git 弹出浏览器/凭据窗口，认证信息保存在 Windows
凭据管理器；不要把 PAT 粘贴到聊天。当前是 MinGit 精简版，其内置
Git Credential Manager 在本机运行异常；因此优先使用 SSH，或安装完整
Git for Windows 后再启用 GCM。

## 5. 需要我操作 Git 时

在本地完成身份与认证后，告诉我：

- 平台（GitHub/Gitee/GitLab）；
- 仓库 URL（可公开）；
- "SSH/GCM 已配置"；
- 是否要我执行 `git init`、首次提交或推送。

我可以在不接触密钥的前提下执行 `git status`、`git add/commit`、`git push`；
若 SSH Key 有 passphrase 或凭据需要交互，推送可能仍需你在本机确认。

## 6. 一句话总结

**Key 写进 `ai-engine-py/.env`（已忽略），Git 密码/Token/私钥交给系统凭据或
SSH agent；只把"已配置"和非敏感信息告诉我。**
