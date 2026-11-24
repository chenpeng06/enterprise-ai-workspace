const rawBaseUrl = import.meta.env.VITE_GATEWAY_BASE_URL ?? "";

/**
 * 空字符串表示走同源相对路径：开发期由 Vite 代理转发到 gateway-go，
 * 生产期由 Nginx / 阿里云 SLB 将 /api 与 /healthz 路由到网关。
 */
export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, "");

export const apiUrl = (path: string): string =>
  `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
