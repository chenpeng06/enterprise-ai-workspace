package quota

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/enterprise-ai-workspace/gateway-go/internal/auth"
)

func (s *Service) StatusHandler(c *gin.Context) {
	identity, ok := auth.IdentityFromContext(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{
			"code": "unauthorized", "message": "请先登录", "retryable": false,
		}})
		return
	}
	limit, err := s.Limit(c.Request.Context(), identity.WorkspaceID)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"code": "dependency_unavailable", "message": "配额服务不可用", "retryable": true,
		}})
		return
	}
	if identity.Role != "viewer" {
		c.JSON(http.StatusOK, gin.H{
			"applicable": false, "limit": limit, "used": 0,
			"remaining": limit, "reset_at": nextReset(time.Now().In(shanghai())),
		})
		return
	}
	status, err := s.Status(c.Request.Context(), identity.WorkspaceID, identity.UserID, limit)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"code": "dependency_unavailable", "message": "配额服务不可用", "retryable": true,
		}})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"applicable": true, "limit": status.Limit, "used": status.Used,
		"remaining": status.Remaining, "reset_at": status.ResetAt,
	})
}
