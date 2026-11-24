package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

var (
	ErrMemberNotFound    = errors.New("成员不存在")
	ErrWorkspaceNotFound = errors.New("workspace 不存在")
)

type Member struct {
	UserID      string     `json:"user_id"`
	Email       string     `json:"email"`
	DisplayName string     `json:"display_name"`
	Role        string     `json:"role"`
	IsActive    bool       `json:"is_active"`
	LastLoginAt *time.Time `json:"last_login_at,omitempty"`
	JoinedAt    time.Time  `json:"joined_at"`
	InvitedBy   *string    `json:"invited_by,omitempty"`
}

type AuthUser struct {
	Member
	PasswordHash string
}

func (p *Postgres) FindUserByEmail(
	ctx context.Context,
	workspaceID, email string,
) (*AuthUser, error) {
	row := p.Pool.QueryRow(ctx, `
		SELECT u.id::text, u.email, u.display_name, u.password_hash,
		       u.is_active, u.last_login_at, wm.role::text, wm.joined_at,
		       wm.invited_by::text
		FROM users u
		JOIN workspace_members wm ON wm.user_id = u.id
		WHERE wm.workspace_id = $1::uuid
		  AND lower(u.email) = lower($2)
	`, workspaceID, email)
	return scanAuthUser(row)
}

func (p *Postgres) GetUserMembership(
	ctx context.Context,
	workspaceID, userID string,
) (*AuthUser, error) {
	row := p.Pool.QueryRow(ctx, `
		SELECT u.id::text, u.email, u.display_name, u.password_hash,
		       u.is_active, u.last_login_at, wm.role::text, wm.joined_at,
		       wm.invited_by::text
		FROM users u
		JOIN workspace_members wm ON wm.user_id = u.id
		WHERE wm.workspace_id = $1::uuid AND u.id = $2::uuid
	`, workspaceID, userID)
	return scanAuthUser(row)
}

func scanAuthUser(row pgx.Row) (*AuthUser, error) {
	var user AuthUser
	if err := row.Scan(
		&user.UserID, &user.Email, &user.DisplayName, &user.PasswordHash,
		&user.IsActive, &user.LastLoginAt, &user.Role, &user.JoinedAt,
		&user.InvitedBy,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrMemberNotFound
		}
		return nil, fmt.Errorf("查询成员失败: %w", err)
	}
	return &user, nil
}

func (p *Postgres) ListMembers(ctx context.Context, workspaceID string) ([]Member, error) {
	rows, err := p.Pool.Query(ctx, `
		SELECT u.id::text, u.email, u.display_name, wm.role::text,
		       u.is_active, u.last_login_at, wm.joined_at, wm.invited_by::text
		FROM workspace_members wm
		JOIN users u ON u.id = wm.user_id
		WHERE wm.workspace_id = $1::uuid
		ORDER BY
		  CASE wm.role
		    WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
		    WHEN 'editor' THEN 2 ELSE 3 END,
		  u.created_at
	`, workspaceID)
	if err != nil {
		return nil, fmt.Errorf("查询成员列表失败: %w", err)
	}
	defer rows.Close()
	members := make([]Member, 0)
	for rows.Next() {
		var member Member
		if err := rows.Scan(
			&member.UserID, &member.Email, &member.DisplayName, &member.Role,
			&member.IsActive, &member.LastLoginAt, &member.JoinedAt, &member.InvitedBy,
		); err != nil {
			return nil, fmt.Errorf("读取成员失败: %w", err)
		}
		members = append(members, member)
	}
	return members, rows.Err()
}

func (p *Postgres) CreateWorkspaceUser(
	ctx context.Context,
	workspaceID, email, displayName, passwordHash, role, invitedBy string,
) (*Member, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("开启用户事务失败: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var userID string
	err = tx.QueryRow(ctx,
		`SELECT id::text FROM users WHERE lower(email) = lower($1)`, email,
	).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		err = tx.QueryRow(ctx, `
			INSERT INTO users (email, display_name, password_hash)
			VALUES (lower($1), $2, $3)
			RETURNING id::text
		`, email, displayName, passwordHash).Scan(&userID)
	}
	if err != nil {
		return nil, fmt.Errorf("创建用户失败: %w", err)
	}

	if _, err := tx.Exec(ctx, `
		INSERT INTO workspace_members (workspace_id, user_id, role, invited_by)
		VALUES ($1::uuid, $2::uuid, $3::workspace_role, NULLIF($4, '')::uuid)
		ON CONFLICT (workspace_id, user_id) DO NOTHING
	`, workspaceID, userID, role, invitedBy); err != nil {
		return nil, fmt.Errorf("写入 workspace 成员失败: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("提交用户事务失败: %w", err)
	}
	return p.GetMember(ctx, workspaceID, userID)
}

func (p *Postgres) GetMember(ctx context.Context, workspaceID, userID string) (*Member, error) {
	row := p.Pool.QueryRow(ctx, `
		SELECT u.id::text, u.email, u.display_name, wm.role::text,
		       u.is_active, u.last_login_at, wm.joined_at, wm.invited_by::text
		FROM workspace_members wm
		JOIN users u ON u.id = wm.user_id
		WHERE wm.workspace_id = $1::uuid AND u.id = $2::uuid
	`, workspaceID, userID)
	var member Member
	if err := row.Scan(
		&member.UserID, &member.Email, &member.DisplayName, &member.Role,
		&member.IsActive, &member.LastLoginAt, &member.JoinedAt, &member.InvitedBy,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrMemberNotFound
		}
		return nil, fmt.Errorf("查询成员失败: %w", err)
	}
	return &member, nil
}

func (p *Postgres) UpdateMemberRole(
	ctx context.Context,
	workspaceID, userID, role string,
) error {
	tag, err := p.Pool.Exec(ctx, `
		UPDATE workspace_members
		SET role = $3::workspace_role
		WHERE workspace_id = $1::uuid AND user_id = $2::uuid
	`, workspaceID, userID, role)
	if err != nil {
		return fmt.Errorf("更新成员角色失败: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrMemberNotFound
	}
	return nil
}

func (p *Postgres) RemoveMember(ctx context.Context, workspaceID, userID string) error {
	tag, err := p.Pool.Exec(ctx, `
		DELETE FROM workspace_members
		WHERE workspace_id = $1::uuid AND user_id = $2::uuid
	`, workspaceID, userID)
	if err != nil {
		return fmt.Errorf("移除成员失败: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrMemberNotFound
	}
	return nil
}

func (p *Postgres) UpdatePassword(
	ctx context.Context,
	workspaceID, userID, passwordHash string,
) error {
	tag, err := p.Pool.Exec(ctx, `
		UPDATE users u
		SET password_hash = $3, updated_at = now()
		FROM workspace_members wm
		WHERE u.id = wm.user_id
		  AND wm.workspace_id = $1::uuid
		  AND u.id = $2::uuid
	`, workspaceID, userID, passwordHash)
	if err != nil {
		return fmt.Errorf("更新密码失败: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrMemberNotFound
	}
	return nil
}

func (p *Postgres) TouchLastLogin(ctx context.Context, userID string) {
	_, _ = p.Pool.Exec(ctx, `UPDATE users SET last_login_at = now() WHERE id = $1::uuid`, userID)
}

func (p *Postgres) CountOwners(ctx context.Context, workspaceID string) (int, error) {
	var count int
	if err := p.Pool.QueryRow(ctx, `
		SELECT COUNT(*)::int FROM workspace_members
		WHERE workspace_id = $1::uuid AND role = 'owner'
	`, workspaceID).Scan(&count); err != nil {
		return 0, fmt.Errorf("统计 owner 失败: %w", err)
	}
	return count, nil
}

func (p *Postgres) WorkspaceSettings(ctx context.Context, workspaceID string) (map[string]any, error) {
	var raw []byte
	if err := p.Pool.QueryRow(ctx,
		`SELECT settings FROM workspaces WHERE id = $1::uuid`,
		workspaceID,
	).Scan(&raw); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrWorkspaceNotFound
		}
		return nil, fmt.Errorf("读取 workspace 设置失败: %w", err)
	}
	settings := make(map[string]any)
	if len(raw) > 0 {
		if err := json.Unmarshal(raw, &settings); err != nil {
			return nil, fmt.Errorf("解析 workspace 设置失败: %w", err)
		}
	}
	return settings, nil
}

func (p *Postgres) UpdateGuestQuota(ctx context.Context, workspaceID string, quota int) error {
	tag, err := p.Pool.Exec(ctx, `
		UPDATE workspaces
		SET settings = jsonb_set(settings, '{guest_daily_query_quota}', to_jsonb($2::int), true),
		    updated_at = now()
		WHERE id = $1::uuid
	`, workspaceID, quota)
	if err != nil {
		return fmt.Errorf("更新游客配额失败: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrWorkspaceNotFound
	}
	return nil
}

func (p *Postgres) UpdateAgentTypes(
	ctx context.Context,
	workspaceID string,
	agentTypes json.RawMessage,
) error {
	tag, err := p.Pool.Exec(ctx, `
		UPDATE workspaces
		SET settings = jsonb_set(settings, '{agent_types}', $2::jsonb, true),
		    updated_at = now()
		WHERE id = $1::uuid
	`, workspaceID, string(agentTypes))
	if err != nil {
		return fmt.Errorf("更新数字员工类型失败: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrWorkspaceNotFound
	}
	return nil
}

// EnsureDemoTenant 保证本地演示 workspace / KB 存在，便于认证种子数据落在正确租户。
func (p *Postgres) EnsureDemoTenant(
	ctx context.Context,
	workspaceID, kbID, workspaceName, kbName string,
) error {
	if _, err := p.Pool.Exec(ctx, `
		INSERT INTO workspaces (id, slug, name, plan, settings)
		VALUES ($1::uuid, 'demo-ops', $2, 'team',
		        jsonb_build_object('guest_daily_query_quota', 20))
		ON CONFLICT (id) DO NOTHING
	`, workspaceID, workspaceName); err != nil {
		return fmt.Errorf("创建演示 workspace 失败: %w", err)
	}
	if _, err := p.Pool.Exec(ctx, `
		INSERT INTO knowledge_bases (
			id, workspace_id, name, description, embedding_model,
			chunk_count, avg_chunk_tokens, is_default
		) VALUES ($1::uuid, $2::uuid, $3, 'Phase 4 演示知识库',
		          'text-embedding-v3', 0, 0, true)
		ON CONFLICT (id) DO NOTHING
	`, kbID, workspaceID, kbName); err != nil {
		return fmt.Errorf("创建演示知识库失败: %w", err)
	}
	return nil
}
