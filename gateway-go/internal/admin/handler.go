package admin

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/mail"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"github.com/enterprise-ai-workspace/gateway-go/internal/auth"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

type Handler struct {
	cfg   *config.Config
	store *store.Postgres
}

func NewHandler(cfg *config.Config, database *store.Postgres) *Handler {
	return &Handler{cfg: cfg, store: database}
}

type createUserRequest struct {
	Email       string `json:"email"`
	DisplayName string `json:"display_name"`
	Password    string `json:"password"`
	Role        string `json:"role"`
}

type updateRoleRequest struct {
	Role string `json:"role"`
}

type resetPasswordRequest struct {
	Password string `json:"password"`
}

type quotaRequest struct {
	Quota int `json:"quota"`
}

type AgentType struct {
	ID           string   `json:"id"`
	Name         string   `json:"name"`
	Description  string   `json:"description"`
	SystemPrompt string   `json:"system_prompt"`
	Mode         string   `json:"mode"`
	AllowedTools []string `json:"allowed_tools"`
	Enabled      bool     `json:"enabled"`
	UpdatedAt    string   `json:"updated_at,omitempty"`
}

type agentTypesRequest struct {
	AgentTypes []AgentType `json:"agent_types"`
}

func (h *Handler) ListUsers(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	members, err := h.store.ListMembers(c.Request.Context(), identity.WorkspaceID)
	if err != nil {
		internalError(c, "读取成员失败")
		return
	}
	c.JSON(http.StatusOK, gin.H{"members": members})
}

func (h *Handler) CreateUser(c *gin.Context) {
	actor, _ := auth.IdentityFromContext(c)
	var request createUserRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		badRequest(c, "请求体格式错误")
		return
	}
	request.Email = strings.TrimSpace(strings.ToLower(request.Email))
	request.DisplayName = strings.TrimSpace(request.DisplayName)
	request.Role = strings.TrimSpace(request.Role)
	if request.Role == "" {
		request.Role = "viewer"
	}
	if !validRole(request.Role) || !auth.CanManageRole(actor.Role, request.Role) {
		forbidden(c, "不能创建该角色")
		return
	}
	if _, err := mail.ParseAddress(request.Email); err != nil || !strings.Contains(request.Email, "@") {
		badRequest(c, "邮箱格式不合法")
		return
	}
	if err := auth.ValidatePassword(request.Password); err != nil {
		badRequest(c, err.Error())
		return
	}
	if request.DisplayName == "" {
		request.DisplayName = strings.Split(request.Email, "@")[0]
	}
	hash, err := auth.HashPassword(request.Password)
	if err != nil {
		internalError(c, "密码处理失败")
		return
	}
	member, err := h.store.CreateWorkspaceUser(
		c.Request.Context(), actor.WorkspaceID, request.Email,
		request.DisplayName, hash, request.Role, actor.UserID,
	)
	if err != nil {
		internalError(c, "创建用户失败")
		return
	}
	c.JSON(http.StatusCreated, gin.H{"member": member})
}

func (h *Handler) UpdateRole(c *gin.Context) {
	actor, _ := auth.IdentityFromContext(c)
	target, ok := h.target(c)
	if !ok {
		return
	}
	var request updateRoleRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		badRequest(c, "请求体格式错误")
		return
	}
	request.Role = strings.TrimSpace(request.Role)
	if !validRole(request.Role) || request.Role == "owner" {
		badRequest(c, "角色只能是 admin/editor/viewer")
		return
	}
	if target.UserID == actor.UserID {
		badRequest(c, "不能修改自己的角色")
		return
	}
	if !auth.CanTouchRole(actor.Role, target.Role) || !auth.CanManageRole(actor.Role, request.Role) {
		forbidden(c, "不能修改该用户的角色")
		return
	}
	if target.Role == "owner" {
		owners, err := h.store.CountOwners(c.Request.Context(), actor.WorkspaceID)
		if err != nil || owners <= 1 {
			badRequest(c, "不能降级最后一个超级管理员")
			return
		}
	}
	if err := h.store.UpdateMemberRole(
		c.Request.Context(), actor.WorkspaceID, target.UserID, request.Role,
	); err != nil {
		internalError(c, "更新角色失败")
		return
	}
	member, _ := h.store.GetMember(c.Request.Context(), actor.WorkspaceID, target.UserID)
	c.JSON(http.StatusOK, gin.H{"member": member})
}

func (h *Handler) RemoveUser(c *gin.Context) {
	actor, _ := auth.IdentityFromContext(c)
	target, ok := h.target(c)
	if !ok {
		return
	}
	if target.UserID == actor.UserID {
		badRequest(c, "不能移除自己")
		return
	}
	if !auth.CanTouchRole(actor.Role, target.Role) {
		forbidden(c, "不能移除该用户")
		return
	}
	if target.Role == "owner" {
		owners, err := h.store.CountOwners(c.Request.Context(), actor.WorkspaceID)
		if err != nil || owners <= 1 {
			badRequest(c, "不能移除最后一个超级管理员")
			return
		}
	}
	if err := h.store.RemoveMember(
		c.Request.Context(), actor.WorkspaceID, target.UserID,
	); err != nil {
		internalError(c, "移除成员失败")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *Handler) ResetPassword(c *gin.Context) {
	actor, _ := auth.IdentityFromContext(c)
	target, ok := h.target(c)
	if !ok {
		return
	}
	if !auth.CanTouchRole(actor.Role, target.Role) {
		forbidden(c, "不能重置该用户密码")
		return
	}
	var request resetPasswordRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		badRequest(c, "请求体格式错误")
		return
	}
	if err := auth.ValidatePassword(request.Password); err != nil {
		badRequest(c, err.Error())
		return
	}
	hash, err := auth.HashPassword(request.Password)
	if err != nil {
		internalError(c, "密码处理失败")
		return
	}
	if err := h.store.UpdatePassword(
		c.Request.Context(), actor.WorkspaceID, target.UserID, hash,
	); err != nil {
		internalError(c, "更新密码失败")
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *Handler) GetSettings(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	settings, err := h.store.WorkspaceSettings(c.Request.Context(), identity.WorkspaceID)
	if err != nil {
		internalError(c, "读取设置失败")
		return
	}
	quota := h.guestQuota(settings)
	agentTypes := decodeAgentTypes(settings["agent_types"])
	c.JSON(http.StatusOK, gin.H{
		"guest_daily_query_quota": quota,
		"agent_types":             agentTypes,
	})
}

func (h *Handler) UpdateGuestQuota(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	var request quotaRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		badRequest(c, "请求体格式错误")
		return
	}
	if request.Quota < 0 || request.Quota > 10000 {
		badRequest(c, "游客每日配额必须在 0-10000 之间")
		return
	}
	if err := h.store.UpdateGuestQuota(
		c.Request.Context(), identity.WorkspaceID, request.Quota,
	); err != nil {
		internalError(c, "更新游客配额失败")
		return
	}
	c.JSON(http.StatusOK, gin.H{"guest_daily_query_quota": request.Quota})
}

func (h *Handler) PublicAgentTypes(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	settings, err := h.store.WorkspaceSettings(c.Request.Context(), identity.WorkspaceID)
	if err != nil {
		internalError(c, "读取数字员工类型失败")
		return
	}
	types := decodeAgentTypes(settings["agent_types"])
	visible := make([]gin.H, 0, len(types))
	for _, item := range types {
		if !item.Enabled {
			continue
		}
		visible = append(visible, gin.H{
			"id":          item.ID,
			"name":        item.Name,
			"description": item.Description,
			"mode":        item.Mode,
		})
	}
	c.JSON(http.StatusOK, gin.H{"agent_types": visible})
}

func (h *Handler) GetAgentTypes(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	settings, err := h.store.WorkspaceSettings(c.Request.Context(), identity.WorkspaceID)
	if err != nil {
		internalError(c, "读取数字员工类型失败")
		return
	}
	c.JSON(http.StatusOK, gin.H{"agent_types": decodeAgentTypes(settings["agent_types"])})
}

func (h *Handler) PutAgentTypes(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	var request agentTypesRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		badRequest(c, "请求体格式错误")
		return
	}
	if len(request.AgentTypes) > 20 {
		badRequest(c, "数字员工类型最多 20 个")
		return
	}
	seenNames := make(map[string]struct{})
	seenIDs := make(map[string]struct{})
	normalized := make([]AgentType, 0, len(request.AgentTypes))
	for _, item := range request.AgentTypes {
		item.Name = strings.TrimSpace(item.Name)
		item.Description = strings.TrimSpace(item.Description)
		item.SystemPrompt = strings.TrimSpace(item.SystemPrompt)
		if item.Name == "" || len(item.Name) > 64 {
			badRequest(c, "数字员工名称必须为 1-64 字符")
			return
		}
		if item.Description == "" {
			item.Description = item.Name
		}
		if len(item.Description) > 300 {
			badRequest(c, "数字员工描述不能超过 300 字符")
			return
		}
		if item.SystemPrompt == "" || len(item.SystemPrompt) > 4000 {
			badRequest(c, "System Prompt 必须为 1-4000 字符")
			return
		}
		if item.Mode == "" {
			item.Mode = "agent"
		}
		if item.Mode != "rag" && item.Mode != "agent" {
			badRequest(c, "mode 必须是 rag 或 agent")
			return
		}
		if item.ID == "" {
			item.ID = uuid.NewString()
		}
		if _, err := uuid.Parse(item.ID); err != nil {
			badRequest(c, "数字员工 ID 不是合法 UUID")
			return
		}
		if _, exists := seenIDs[item.ID]; exists {
			badRequest(c, "数字员工 ID 重复")
			return
		}
		if _, exists := seenNames[strings.ToLower(item.Name)]; exists {
			badRequest(c, "数字员工名称重复")
			return
		}
		seenIDs[item.ID] = struct{}{}
		seenNames[strings.ToLower(item.Name)] = struct{}{}
		item.AllowedTools = normalizeTools(item.AllowedTools)
		item.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
		normalized = append(normalized, item)
	}
	raw, err := json.Marshal(normalized)
	if err != nil {
		internalError(c, "序列化数字员工类型失败")
		return
	}
	if err := h.store.UpdateAgentTypes(c.Request.Context(), identity.WorkspaceID, raw); err != nil {
		internalError(c, "保存数字员工类型失败")
		return
	}
	c.JSON(http.StatusOK, gin.H{"agent_types": normalized})
}

func (h *Handler) target(c *gin.Context) (*store.Member, bool) {
	identity, _ := auth.IdentityFromContext(c)
	targetID := c.Param("user_id")
	if _, err := uuid.Parse(targetID); err != nil {
		badRequest(c, "user_id 不是合法 UUID")
		return nil, false
	}
	target, err := h.store.GetMember(c.Request.Context(), identity.WorkspaceID, targetID)
	if err != nil {
		if errors.Is(err, store.ErrMemberNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": gin.H{
				"code": "not_found", "message": "成员不存在", "retryable": false,
			}})
			return nil, false
		}
		internalError(c, "读取成员失败")
		return nil, false
	}
	return target, true
}

func (h *Handler) guestQuota(settings map[string]any) int {
	if raw, ok := settings["guest_daily_query_quota"]; ok {
		if value, ok := raw.(float64); ok {
			return int(value)
		}
	}
	return h.cfg.GuestQuotaDefault
}

func decodeAgentTypes(raw any) []AgentType {
	if raw == nil {
		return []AgentType{}
	}
	data, err := json.Marshal(raw)
	if err != nil {
		return []AgentType{}
	}
	var types []AgentType
	if err := json.Unmarshal(data, &types); err != nil {
		return []AgentType{}
	}
	return types
}

func normalizeTools(tools []string) []string {
	allowed := map[string]struct{}{
		"search_knowledge_base": {},
		"analyze_service_logs":  {},
		"query_service_status":  {},
	}
	result := make([]string, 0, len(tools))
	seen := make(map[string]struct{})
	for _, tool := range tools {
		tool = strings.TrimSpace(tool)
		if _, ok := allowed[tool]; !ok {
			continue
		}
		if _, ok := seen[tool]; ok {
			continue
		}
		seen[tool] = struct{}{}
		result = append(result, tool)
	}
	if len(result) == 0 {
		result = []string{"search_knowledge_base"}
	}
	return result
}

func validRole(role string) bool {
	return role == "owner" || role == "admin" || role == "editor" || role == "viewer"
}

func badRequest(c *gin.Context, message string) {
	c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
		"code": "invalid_request", "message": message, "retryable": false,
	}})
}

func forbidden(c *gin.Context, message string) {
	c.JSON(http.StatusForbidden, gin.H{"error": gin.H{
		"code": "forbidden", "message": message, "retryable": false,
	}})
}

func internalError(c *gin.Context, message string) {
	c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{
		"code": "internal_error", "message": message, "retryable": true,
	}})
}
