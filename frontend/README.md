# frontend · React + TypeScript 工作台

企业级智能知识库与数字员工工作台的前端工程。Phase 3 已交付对话、原文角标联动、
检索透视抽屉与管理监控看板。

## 技术栈

| 能力 | 选型 |
| --- | --- |
| 构建 | Vite 6 + TypeScript 5.7（strict） |
| UI | React 18 + React Router 6 + TailwindCSS 3.4 |
| 数据 | TanStack Query 5（服务端状态） |
| Markdown | react-markdown + remark-gfm（保留角标交互） |
| 质量 | ESLint 9（flat config）+ `tsc --noEmit` |

## 页面

| 路由 | 组件 | 能力 |
| --- | --- | --- |
| `/` | `HomePage` | 项目总览、服务健康、路线图 |
| `/chat` | `ChatPage` | SSE 对话、Agent 进度、检索透视、角标联动原文预览 |
| `/admin` | `AdminPage` | 限流拦截、平均/P95 TTFT、Token、知识库命中率 |

## 目录结构

```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts              # /api、/healthz 开发代理
├── tailwind.config.ts
├── postcss.config.js
├── eslint.config.js
├── .env.example
└── src/
    ├── main.tsx                # React Query Provider + 挂载
    ├── App.tsx                 # /、/chat、/admin 路由
    ├── index.css               # Tailwind 入口与基础样式
    ├── components/
    │   ├── AppShell.tsx
    │   └── StatusPanel.tsx     # 探测 gateway-go /healthz
    ├── pages/
    │   ├── HomePage.tsx
    │   ├── ChatPage.tsx
    │   ├── AdminPage.tsx
    │   └── NotFoundPage.tsx
    ├── lib/
    │   ├── env.ts              # API base URL 归一化
    │   ├── api.ts              # 公共 API + SSE 对话入口
    │   ├── sse.ts              # 无依赖 SSE 解析器
    │   └── cn.ts
    ├── types/
    │   ├── contract.ts         # 内部契约 v1 的 TS 类型镜像
    │   └── public.ts           # 网关公共 API / 监控类型
    └── features/
        ├── chat/               # 对话、进度、Markdown/角标、原文预览
        └── retrieval-inspector/# 检索漏斗与 Rerank 前后对比
```

## 本地运行

```bash
cd frontend
npm install
cp .env.example .env.local   # Windows: Copy-Item .env.example .env.local
npm run dev                  # http://127.0.0.1:5173
```

开发代理默认把 `/api`、`/healthz`、`/readyz` 转发到 `http://127.0.0.1:8080`，
可通过 `VITE_GATEWAY_PROXY_TARGET` 覆盖。

## 交互要点

- 对话事件与内部契约一致，`streamChat` 消费网关公共 SSE；
- 回答由 `react-markdown` 渲染，`[n]` 被预处理为内部链接并替换成可点击角标；
- 点击角标后按 `chunk_id` 拉取 `/api/v1/chunks/{id}`，右侧展示页码、bbox 命中框、
  章节路径与 quote 高亮；
- 检索透视抽屉展示 Vector/BM25/RRF/Rerank 得分、候选/入选与 `fused → rerank`
  排名变化；
- 监控看板每 15 秒刷新一次，数据源为网关 `request_logs` / `rate_limit_events` /
  `retrieval_traces`。

## 质量命令

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # eslint .
npm run build       # 类型检查 + 生产构建
```

## 契约约束

- 权威契约：`docs/contracts/ai-engine-internal-v1.schema.json`（v1.0.0）。
- `src/types/contract.ts` 是前端消费子集的类型镜像；修改契约必须同步更新，并运行
  `python scripts/validate_contracts.py`。
- SSE 解析器支持 POST 流式响应、跨 chunk UTF-8、心跳注释帧与 `id` 续传字段；
  Phase 3 的网关代理必须保持事件顺序与 JSON 原样。
