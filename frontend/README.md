# frontend · React + TypeScript 工作台

企业级智能知识库与数字员工工作台的前端工程。Phase 1 只交付可运行的工程骨架、
契约类型镜像与 SSE 客户端基础设施；对话、检索透视、管理后台组件在 Phase 3 实现。

## 技术栈

| 能力 | 选型 |
| --- | --- |
| 构建 | Vite 6 + TypeScript 5.7（strict） |
| UI | React 18 + React Router 6 + TailwindCSS 3.4 |
| 数据 | TanStack Query 5（服务端状态） |
| 质量 | ESLint 9（flat config）+ `tsc --noEmit` |

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
    ├── App.tsx                 # 路由骨架
    ├── index.css               # Tailwind 入口与基础样式
    ├── components/
    │   ├── AppShell.tsx
    │   └── StatusPanel.tsx     # 探测 gateway-go /healthz
    ├── pages/
    │   ├── HomePage.tsx
    │   └── NotFoundPage.tsx
    ├── lib/
    │   ├── env.ts              # API base URL 归一化
    │   ├── api.ts              # 健康检查 + 对话流入口
    │   ├── sse.ts              # 无依赖 SSE 解析器
    │   └── cn.ts
    ├── types/
    │   └── contract.ts         # 内部契约 v1 的 TS 类型镜像
    └── features/               # Phase 3 组件按领域落位
        ├── chat/               # 对话与角标联动
        ├── retrieval-inspector/# 检索透视抽屉
        └── admin/              # 限流 / TTFT / 命中率看板
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
