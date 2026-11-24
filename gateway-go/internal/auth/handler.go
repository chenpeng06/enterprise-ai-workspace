package auth

import (
	"errors"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

type Handler struct {
	service *Service
}

func NewHandler(service *Service) *Handler {
	return &Handler{service: service}
}

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func (h *Handler) Login(c *gin.Context) {
	var request loginRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
			"code": "invalid_request", "message": "邮箱或密码格式错误", "retryable": false,
		}})
		return
	}
	request.Email = strings.TrimSpace(request.Email)
	if request.Email == "" || len(request.Password) < 1 || len(request.Password) > 128 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
			"code": "invalid_request", "message": "邮箱和密码不能为空", "retryable": false,
		}})
		return
	}
	token, identity, err := h.service.Login(c.Request.Context(), request.Email, request.Password)
	if err != nil {
		if errors.Is(err, ErrInvalidCredentials) {
			c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{
				"code": "unauthorized", "message": "邮箱或密码错误", "retryable": false,
			}})
			return
		}
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"code": "dependency_unavailable", "message": "登录服务暂不可用", "retryable": true,
		}})
		return
	}
	name, value, maxAge, secure := h.service.Cookie(token)
	http.SetCookie(c.Writer, &http.Cookie{
		Name:     name,
		Value:    value,
		Path:     "/",
		MaxAge:   maxAge,
		HttpOnly: true,
		Secure:   secure,
		SameSite: http.SameSiteLaxMode,
	})
	c.JSON(http.StatusOK, gin.H{"identity": identity})
}

func (h *Handler) Logout(c *gin.Context) {
	token, _ := c.Cookie(SessionCookieName)
	h.service.Logout(c.Request.Context(), token)
	name, _, _, _ := h.service.Cookie("")
	http.SetCookie(c.Writer, &http.Cookie{
		Name:     name,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		HttpOnly: true,
		SameSite: http.SameSiteLaxMode,
	})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *Handler) Me(c *gin.Context) {
	identity, ok := IdentityFromContext(c)
	if !ok {
		abortUnauthorized(c, "请先登录")
		return
	}
	c.JSON(http.StatusOK, gin.H{"identity": identity})
}
