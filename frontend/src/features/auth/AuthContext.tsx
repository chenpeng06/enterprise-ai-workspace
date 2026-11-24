/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import {
  fetchMe,
  login as loginRequest,
  logout as logoutRequest,
} from "@/lib/api";
import type { Identity } from "@/types/auth";

interface AuthContextValue {
  identity: Identity | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Identity>;
  logout: () => Promise<void>;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["auth-me"],
    queryFn: ({ signal }) => fetchMe(signal),
    retry: false,
    staleTime: 30_000,
  });

  const login = useCallback(
    async (email: string, password: string) => {
      const identity = await loginRequest(email, password);
      queryClient.setQueryData(["auth-me"], identity);
      return identity;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      queryClient.setQueryData(["auth-me"], null);
      queryClient.removeQueries({ queryKey: ["auth-me"] });
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(() => {
    const identity = me.data ?? null;
    return {
      identity,
      loading: me.isPending,
      login,
      logout,
      can: (permission: string) =>
        Boolean(
          identity &&
            (identity.permissions.includes("*") || identity.permissions.includes(permission)),
        ),
    };
  }, [login, logout, me.data, me.isPending]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 AuthProvider 内使用");
  }
  return context;
}

export function RequireAuth() {
  const { identity, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="card flex min-h-[240px] items-center justify-center text-sm text-slate-500">
        正在校验登录状态…
      </div>
    );
  }
  if (!identity) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

export function RequirePermission({ permission }: { permission: string }) {
  const { can, identity } = useAuth();
  if (!can(permission)) {
    return (
      <div className="card border-rose-200 bg-rose-50 text-sm text-rose-700">
        当前角色（{identity?.role_label ?? "未登录"}）没有访问该页面的权限。
      </div>
    );
  }
  return <Outlet />;
}
