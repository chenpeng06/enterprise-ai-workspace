import { StatusPanel } from "@/components/StatusPanel";
import { SSE_EVENT_NAMES } from "@/types/contract";

const SERVICES = [
  {
    name: "frontend",
    path: "frontend/",
    role: "对话与原文高亮联动、检索透视抽屉、管理后台看板",
    stack: "React 18 · TypeScript · Vite · TailwindCSS",
  },
  {
    name: "gateway-go",
    path: "gateway-go/",
    role: "鉴权、分布式限流、SSE 流式透传、TTFT 与 Token 统计",
    stack: "Go 1.23 · Gin · Redis · pgx",
  },
  {
    name: "ai-engine-py",
    path: "ai-engine-py/",
    role: "文档解析、混合检索、Rerank、LangGraph 数字员工编排",
    stack: "Python 3.12 · FastAPI · LangGraph · pgvector",
  },
  {
    name: "deploy",
    path: "deploy/",
    role: "本地一键编排、数据库初始化、阿里云低成本部署",
    stack: "Docker Compose · RDS · Redis · OSS · SAE",
  },
] as const;

const PHASES = [
  {
    phase: "Phase 1",
    title: "脚手架与跨语言契约",
    description: "四端目录、依赖配置、JSON Schema 与 pgvector 建模",
    status: "本次交付",
    active: true,
  },
  {
    phase: "Phase 2",
    title: "Python AI 引擎",
    description: "混合检索、RRF、Rerank 与 LangGraph 数字员工",
    status: "待开始",
    active: false,
  },
  {
    phase: "Phase 3",
    title: "Go 网关与前端工作台",
    description: "Redis 令牌桶、SSE 代理、溯源高亮与监控看板",
    status: "待开始",
    active: false,
  },
  {
    phase: "Phase 4",
    title: "容器化与阿里云部署",
    description: "Dockerfile、Compose 与 1000 元/月以内落地方案",
    status: "待开始",
    active: false,
  },
] as const;

export function HomePage() {
  return (
    <div className="space-y-8">
      <section className="overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-white to-brand-50 p-8 shadow-card sm:p-10">
        <div className="max-w-3xl space-y-4">
          <span className="inline-flex items-center rounded-full border border-brand-100 bg-brand-50 px-3 py-1 font-mono text-xs font-semibold text-brand-700">
            PHASE 1 · FOUNDATION
          </span>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            多语言微服务底座已经就位
          </h1>
          <p className="text-base leading-7 text-slate-600">
            面向企业知识库与数字员工场景：Go 网关承担高并发入口与流式代理，Python
            引擎负责混合检索与多智能体编排，前端工作台实现角标溯源与检索透视。
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <span className="chip">Hybrid Search</span>
            <span className="chip">pgvector / RRF</span>
            <span className="chip">LangGraph</span>
            <span className="chip">SSE Streaming</span>
            <span className="chip">Multi-tenant</span>
          </div>
        </div>
      </section>

      <StatusPanel />

      <section className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-slate-900">子项目边界</h2>
            <p className="mt-1 text-sm text-slate-500">
              网关只做入口与治理，AI 引擎只做检索与生成，禁止业务逻辑交叉。
            </p>
          </div>
          <span className="font-mono text-xs text-slate-400">monorepo · 4 workspaces</span>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {SERVICES.map((service) => (
            <article key={service.name} className="card space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-mono text-sm font-semibold text-slate-900">{service.name}</h3>
                <span className="font-mono text-xs text-slate-400">{service.path}</span>
              </div>
              <p className="text-sm leading-6 text-slate-600">{service.role}</p>
              <p className="border-t border-slate-100 pt-3 font-mono text-xs text-slate-500">
                {service.stack}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <article className="card space-y-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-slate-900">
              流式问答事件契约
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              一次回答会按序推送以下事件；<code className="font-mono text-xs">retrieval</code>{" "}
              事件携带完整检索漏斗，前端据此渲染得分与排名变化。
            </p>
          </div>
          <ul className="flex flex-wrap gap-2">
            {SSE_EVENT_NAMES.map((name) => (
              <li key={name} className="chip">
                {name}
              </li>
            ))}
          </ul>
          <p className="rounded-xl bg-slate-50 p-3 font-mono text-xs leading-6 text-slate-500">
            meta → thinking / tool_calling / reranking → retrieval → citation* → generating* →
            usage → done
          </p>
        </article>

        <article className="card space-y-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-slate-900">开发路线图</h2>
            <p className="mt-1 text-sm text-slate-500">按阶段增量交付，接口契约先行。</p>
          </div>
          <ol className="space-y-3">
            {PHASES.map((phase) => (
              <li key={phase.phase} className="flex gap-3">
                <span
                  className={
                    phase.active
                      ? "mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-brand-500"
                      : "mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-slate-300"
                  }
                  aria-hidden="true"
                />
                <div>
                  <p className="text-sm font-medium text-slate-800">
                    <span className="font-mono text-xs text-slate-400">{phase.phase}</span>{" "}
                    {phase.title}
                  </p>
                  <p className="text-xs leading-5 text-slate-500">{phase.description}</p>
                </div>
                <span className="ml-auto self-start text-xs text-slate-400">{phase.status}</span>
              </li>
            ))}
          </ol>
        </article>
      </section>
    </div>
  );
}
