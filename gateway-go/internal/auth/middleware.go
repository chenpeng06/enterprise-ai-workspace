package auth

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

const identityContextKey = "auth_identity"

func IdentityFromContext(c *gin.Context) (*Identity, bool) {
	value, exists := c.Get(identityContextKey)
	if !exists {
		return nil, false
	}
	identity, ok := value.(*Identity)
	return identity, ok
}

func RequireAuth(service *Service) gin.HandlerFunc {
	return func(c *gin.Context) {
		token, err := c.Cookie(SessionCookieName)
		if err != nil || strings.TrimSpace(token) == "" {
			abortUnauthorized(c, "请先登录")
			return
		}
		identity, err := service.Authenticate(c.Request.Context(), token)
		if err != nil {
			abortUnauthorized(c, "会话已过期，请重新登录")
			return
		}
		c.Set(identityContextKey, identity)
		c.Set("auth_user_id", identity.UserID)
		c.Set("auth_workspace_id", identity.WorkspaceID)
		c.Next()
	}
}

func RequirePermission(permission string) gin.HandlerFunc {
	return func(c *gin.Context) {
		identity, ok := IdentityFromContext(c)
		if !ok {
			abortUnauthorized(c, "请先登录")
			return
		}
		if !HasPermission(identity, permission) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": gin.H{
				"code":      "forbidden",
				"message":   "当前角色没有该操作权限",
				"retryable": false,
			}})
			return
		}
		c.Next()
	}
}

func abortUnauthorized(c *gin.Context, message string) {
	c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": gin.H{
		"code":      "unauthorized",
		"message":   message,
		"retryable": false,
	}})
}
