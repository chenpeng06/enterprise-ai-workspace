// Package auth 提供本地邮箱密码登录、Redis 会话与 RBAC。
package auth

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/redis/go-redis/v9"
	"golang.org/x/crypto/bcrypt"

	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

const (
	SessionCookieName = "eaw_session"
	sessionKeyPrefix  = "session:"

	PermissionAll       = "*"
	PermissionChatUse   = "chat.use"
	PermissionDocsRead  = "docs.read"
	PermissionDocsWrite = "docs.upload"
	PermissionAgents    = "agents.manage"
	PermissionUsersRead = "users.read"
	PermissionUsersEdit = "users.manage"
	PermissionAdmins    = "admins.manage"
	PermissionQuota     = "quota.manage"
	PermissionMetrics   = "metrics.read"
)

var ErrInvalidCredentials = errors.New("邮箱或密码错误")
var ErrUnauthorized = errors.New("会话无效或已过期")

type Identity struct {
	UserID      string   `json:"user_id"`
	WorkspaceID string   `json:"workspace_id"`
	Email       string   `json:"email"`
	DisplayName string   `json:"display_name"`
	Role        string   `json:"role"`
	RoleLabel   string   `json:"role_label"`
	Permissions []string `json:"permissions"`
}

type Service struct {
	cfg   *config.Config
	store *store.Postgres
	redis *redis.Client
}

type sessionData struct {
	UserID      string `json:"user_id"`
	WorkspaceID string `json:"workspace_id"`
}

func New(cfg *config.Config, database *store.Postgres, redisClient *redis.Client) *Service {
	return &Service{cfg: cfg, store: database, redis: redisClient}
}

func (s *Service) Login(
	ctx context.Context,
	email, password string,
) (string, *Identity, error) {
	user, err := s.store.FindUserByEmail(ctx, s.cfg.DevWorkspaceID, strings.TrimSpace(email))
	if err != nil || !user.IsActive {
		// 统一错误，避免枚举账号。
		return "", nil, ErrInvalidCredentials
	}
	if bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)) != nil {
		return "", nil, ErrInvalidCredentials
	}

	token, err := randomToken()
	if err != nil {
		return "", nil, fmt.Errorf("生成会话失败: %w", err)
	}
	raw, err := json.Marshal(sessionData{
		UserID:      user.UserID,
		WorkspaceID: s.cfg.DevWorkspaceID,
	})
	if err != nil {
		return "", nil, fmt.Errorf("序列化会话失败: %w", err)
	}
	if s.redis == nil {
		return "", nil, fmt.Errorf("Redis 未初始化，无法创建会话")
	}
	if err := s.redis.Set(ctx, sessionKeyPrefix+token, raw, s.cfg.SessionTTL).Err(); err != nil {
		return "", nil, fmt.Errorf("写入会话失败: %w", err)
	}
	s.store.TouchLastLogin(ctx, user.UserID)

	identity := &Identity{
		UserID:      user.UserID,
		WorkspaceID: s.cfg.DevWorkspaceID,
		Email:       user.Email,
		DisplayName: user.DisplayName,
		Role:        user.Role,
		RoleLabel:   RoleLabel(user.Role),
		Permissions: PermissionsForRole(user.Role),
	}
	return token, identity, nil
}

func (s *Service) Authenticate(ctx context.Context, token string) (*Identity, error) {
	if token == "" || s.redis == nil {
		return nil, ErrUnauthorized
	}
	raw, err := s.redis.Get(ctx, sessionKeyPrefix+token).Bytes()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return nil, ErrUnauthorized
		}
		return nil, fmt.Errorf("读取会话失败: %w", err)
	}
	var data sessionData
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, ErrUnauthorized
	}
	user, err := s.store.GetUserMembership(ctx, data.WorkspaceID, data.UserID)
	if err != nil || !user.IsActive {
		return nil, ErrUnauthorized
	}
	return &Identity{
		UserID:      user.UserID,
		WorkspaceID: data.WorkspaceID,
		Email:       user.Email,
		DisplayName: user.DisplayName,
		Role:        user.Role,
		RoleLabel:   RoleLabel(user.Role),
		Permissions: PermissionsForRole(user.Role),
	}, nil
}

func (s *Service) Logout(ctx context.Context, token string) {
	if token != "" && s.redis != nil {
		_ = s.redis.Del(ctx, sessionKeyPrefix+token).Err()
	}
}

func (s *Service) Cookie(token string) (name, value string, maxAge int, secure bool) {
	return SessionCookieName, token, int(s.cfg.SessionTTL.Seconds()), s.cfg.SessionCookieSecure
}

func RoleLabel(role string) string {
	switch role {
	case "owner":
		return "超级管理员"
	case "admin":
		return "受控管理员"
	case "editor":
		return "运营人员"
	case "viewer":
		return "游客"
	default:
		return role
	}
}

func PermissionsForRole(role string) []string {
	switch role {
	case "owner":
		return []string{PermissionAll}
	case "admin":
		return []string{
			PermissionChatUse, PermissionDocsRead, PermissionDocsWrite,
			PermissionAgents, PermissionUsersRead, PermissionUsersEdit,
			PermissionMetrics,
		}
	case "editor", "viewer":
		return []string{PermissionChatUse, PermissionDocsRead}
	default:
		return []string{}
	}
}

func HasPermission(identity *Identity, permission string) bool {
	if identity == nil {
		return false
	}
	for _, current := range identity.Permissions {
		if current == PermissionAll || current == permission {
			return true
		}
	}
	return false
}

func CanManageRole(actorRole, targetRole string) bool {
	switch actorRole {
	case "owner":
		return targetRole == "admin" || targetRole == "editor" || targetRole == "viewer"
	case "admin":
		return targetRole == "editor" || targetRole == "viewer"
	default:
		return false
	}
}

func CanTouchRole(actorRole, targetRole string) bool {
	if actorRole == "owner" {
		return true
	}
	if actorRole == "admin" {
		return targetRole == "editor" || targetRole == "viewer"
	}
	return false
}

func HashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", fmt.Errorf("密码哈希失败: %w", err)
	}
	return string(hash), nil
}

func ValidatePassword(password string) error {
	if len(password) < 8 || len(password) > 128 {
		return fmt.Errorf("密码长度必须在 8-128 字符")
	}
	return nil
}

func randomToken() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

// EnsureDemoAccounts 在 development 下创建演示账号；生产环境禁用。
func EnsureDemoAccounts(ctx context.Context, cfg *config.Config, database *store.Postgres) error {
	if !cfg.SeedDemoUsers {
		return nil
	}
	if err := database.EnsureDemoTenant(
		ctx, cfg.DevWorkspaceID, cfg.DevKBID, "研发运维演示空间", "研发运维规范库",
	); err != nil {
		return err
	}
	accounts := []struct {
		email    string
		password string
		name     string
		role     string
	}{
		{cfg.DemoSuperEmail, cfg.DemoSuperPassword, "超级管理员", "owner"},
		{cfg.DemoAdminEmail, cfg.DemoAdminPassword, "受控管理员", "admin"},
		{cfg.DemoGuestEmail, cfg.DemoGuestPassword, "游客", "viewer"},
	}
	for _, account := range accounts {
		if strings.TrimSpace(account.email) == "" {
			continue
		}
		existing, err := database.FindUserByEmail(ctx, cfg.DevWorkspaceID, account.email)
		if err == nil && existing != nil {
			// 演示账号每次启动都校准角色，避免手工改乱后无法登录后台。
			if updateErr := database.UpdateMemberRole(
				ctx, cfg.DevWorkspaceID, existing.UserID, account.role,
			); updateErr != nil {
				return fmt.Errorf("校准演示账号 %s 角色失败: %w", account.email, updateErr)
			}
			continue
		}
		hash, err := HashPassword(account.password)
		if err != nil {
			return err
		}
		if _, err := database.CreateWorkspaceUser(
			ctx, cfg.DevWorkspaceID, account.email, account.name, hash, account.role, "",
		); err != nil {
			return fmt.Errorf("创建演示账号 %s 失败: %w", account.email, err)
		}
	}
	return nil
}
