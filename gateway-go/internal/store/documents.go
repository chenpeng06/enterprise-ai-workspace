package store

import (
	"context"
	"fmt"
	"time"
)

type DocumentSummary struct {
	DocumentID   string    `json:"document_id"`
	Title        string    `json:"title"`
	FileName     string    `json:"file_name"`
	Status       string    `json:"status"`
	SizeBytes    int64     `json:"size_bytes"`
	PageCount    int       `json:"page_count"`
	ChunkCount   int       `json:"chunk_count"`
	TaskStatus   string    `json:"task_status"`
	TaskStage    string    `json:"task_stage"`
	Progress     int       `json:"progress"`
	ErrorMessage string    `json:"error_message,omitempty"`
	CreatedAt    time.Time `json:"created_at"`
}

func (p *Postgres) KnowledgeBaseExists(
	ctx context.Context,
	workspaceID, knowledgeBaseID string,
) (bool, error) {
	var exists bool
	if err := p.Pool.QueryRow(ctx, `
		SELECT EXISTS(
			SELECT 1 FROM knowledge_bases
			WHERE workspace_id = $1::uuid AND id = $2::uuid AND deleted_at IS NULL
		)
	`, workspaceID, knowledgeBaseID).Scan(&exists); err != nil {
		return false, fmt.Errorf("检查知识库失败: %w", err)
	}
	return exists, nil
}

func (p *Postgres) ListDocuments(
	ctx context.Context,
	workspaceID string,
	limit int,
) ([]DocumentSummary, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := p.Pool.Query(ctx, `
		SELECT
			d.id::text,
			d.title,
			d.file_name,
			d.status::text,
			d.size_bytes,
			d.page_count,
			d.chunk_count,
			COALESCE(t.status::text, ''),
			COALESCE(t.stage::text, ''),
			COALESCE(t.progress, 0),
			COALESCE(t.error->>'message', ''),
			d.created_at
		FROM documents d
		LEFT JOIN LATERAL (
			SELECT status, stage, progress, error
			FROM ingest_tasks
			WHERE document_id = d.id
			ORDER BY created_at DESC
			LIMIT 1
		) t ON true
		WHERE d.workspace_id = $1::uuid AND d.deleted_at IS NULL
		ORDER BY d.created_at DESC
		LIMIT $2
	`, workspaceID, limit)
	if err != nil {
		return nil, fmt.Errorf("查询文档列表失败: %w", err)
	}
	defer rows.Close()
	documents := make([]DocumentSummary, 0)
	for rows.Next() {
		var item DocumentSummary
		if err := rows.Scan(
			&item.DocumentID, &item.Title, &item.FileName, &item.Status,
			&item.SizeBytes, &item.PageCount, &item.ChunkCount,
			&item.TaskStatus, &item.TaskStage, &item.Progress,
			&item.ErrorMessage, &item.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("读取文档失败: %w", err)
		}
		documents = append(documents, item)
	}
	return documents, rows.Err()
}
