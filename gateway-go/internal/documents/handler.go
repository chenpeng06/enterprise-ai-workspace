// Package documents 提供 PDF 上传与文档状态查询。
package documents

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"github.com/enterprise-ai-workspace/gateway-go/internal/auth"
	"github.com/enterprise-ai-workspace/gateway-go/internal/client/aiengine"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

type Handler struct {
	cfg    *config.Config
	store  *store.Postgres
	engine *aiengine.Client
}

func New(cfg *config.Config, database *store.Postgres, engine *aiengine.Client) *Handler {
	return &Handler{cfg: cfg, store: database, engine: engine}
}

func (h *Handler) List(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	documents, err := h.store.ListDocuments(c.Request.Context(), identity.WorkspaceID, 50)
	if err != nil {
		c.JSON(http.StatusInternalServerError, errorBody("读取文档列表失败", true))
		return
	}
	c.JSON(http.StatusOK, gin.H{"documents": documents})
}

func (h *Handler) Upload(c *gin.Context) {
	identity, _ := auth.IdentityFromContext(c)
	c.Request.Body = http.MaxBytesReader(
		c.Writer, c.Request.Body, h.cfg.MaxUploadBytes+(1<<20),
	)
	fileHeader, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, errorBody("缺少 PDF 文件或文件过大", false))
		return
	}
	if err := validatePDF(fileHeader); err != nil {
		c.JSON(http.StatusBadRequest, errorBody(err.Error(), false))
		return
	}
	kbID := strings.TrimSpace(c.PostForm("knowledge_base_id"))
	if kbID == "" {
		kbID = h.cfg.DevKBID
	}
	if _, err := uuid.Parse(kbID); err != nil {
		c.JSON(http.StatusBadRequest, errorBody("knowledge_base_id 不合法", false))
		return
	}
	exists, err := h.store.KnowledgeBaseExists(c.Request.Context(), identity.WorkspaceID, kbID)
	if err != nil || !exists {
		c.JSON(http.StatusNotFound, errorBody("知识库不存在", false))
		return
	}
	title := strings.TrimSpace(c.PostForm("title"))
	if title == "" {
		title = strings.TrimSuffix(fileHeader.Filename, filepath.Ext(fileHeader.Filename))
	}
	if title == "" || len([]rune(title)) > 300 {
		c.JSON(http.StatusBadRequest, errorBody("文档标题必须为 1-300 字符", false))
		return
	}

	documentID := uuid.NewString()
	absoluteDir, err := filepath.Abs(h.cfg.UploadDir)
	if err != nil {
		c.JSON(http.StatusInternalServerError, errorBody("上传目录配置无效", false))
		return
	}
	if err := os.MkdirAll(absoluteDir, 0o755); err != nil {
		c.JSON(http.StatusInternalServerError, errorBody("创建上传目录失败", true))
		return
	}
	targetPath := filepath.Join(absoluteDir, documentID+".pdf")
	checksum, size, err := saveUpload(fileHeader, targetPath)
	if err != nil {
		c.JSON(http.StatusInternalServerError, errorBody("保存 PDF 失败", true))
		return
	}
	payload := ingestPayload{
		WorkspaceID:     identity.WorkspaceID,
		KnowledgeBaseID: kbID,
		DocumentID:      documentID,
		RequestedBy:     identity.UserID,
		IdempotencyKey:  "upload-" + documentID,
		Document: ingestDocument{
			Title:     title,
			FileName:  fileHeader.Filename,
			MimeType:  "application/pdf",
			SizeBytes: size,
			SHA256:    checksum,
			Language:  "zh",
			Source: ingestSource{
				Type: "local",
				URI:  targetPath,
			},
		},
		Chunking: ingestChunking{
			Strategy:        "hierarchical",
			ParentChunkSize: 1200,
			ChildChunkSize:  300,
			ChildOverlap:    50,
			MinChunkSize:    60,
			Splitter:        "sentence",
			KeepTableIntact: true,
		},
		Embedding: ingestEmbedding{
			Model: "text-embedding-v3", Dimensions: 1024, BatchSize: 10, Normalize: true,
		},
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		_ = os.Remove(targetPath)
		c.JSON(http.StatusInternalServerError, errorBody("构造摄取请求失败", false))
		return
	}
	status, body, err := h.engine.CreateIngest(c.Request.Context(), raw)
	if err != nil {
		_ = os.Remove(targetPath)
		c.JSON(http.StatusBadGateway, errorBody("AI 引擎暂不可用，请稍后重试", true))
		return
	}
	if status != http.StatusAccepted {
		_ = os.Remove(targetPath)
		c.Data(status, "application/json; charset=utf-8", body)
		return
	}
	c.Data(status, "application/json; charset=utf-8", body)
}

func validatePDF(header *multipart.FileHeader) error {
	if header.Size <= 0 {
		return fmt.Errorf("PDF 文件为空")
	}
	if !strings.EqualFold(filepath.Ext(header.Filename), ".pdf") {
		return fmt.Errorf("仅支持 .pdf 文件")
	}
	contentType := strings.ToLower(header.Header.Get("Content-Type"))
	if contentType != "" && contentType != "application/pdf" &&
		contentType != "application/octet-stream" {
		return fmt.Errorf("文件类型必须是 application/pdf")
	}
	return nil
}

func saveUpload(header *multipart.FileHeader, targetPath string) (string, int64, error) {
	source, err := header.Open()
	if err != nil {
		return "", 0, fmt.Errorf("打开上传文件失败: %w", err)
	}
	defer func() { _ = source.Close() }()
	target, err := os.OpenFile(targetPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return "", 0, fmt.Errorf("创建目标文件失败: %w", err)
	}
	defer func() { _ = target.Close() }()
	hasher := sha256.New()
	size, err := io.Copy(io.MultiWriter(target, hasher), source)
	if err != nil {
		_ = os.Remove(targetPath)
		return "", 0, fmt.Errorf("写入 PDF 失败: %w", err)
	}
	return hex.EncodeToString(hasher.Sum(nil)), size, nil
}

func errorBody(message string, retryable bool) gin.H {
	return gin.H{"error": gin.H{
		"code": "invalid_request", "message": message, "retryable": retryable,
	}}
}

type ingestPayload struct {
	WorkspaceID     string          `json:"workspace_id"`
	KnowledgeBaseID string          `json:"knowledge_base_id"`
	DocumentID      string          `json:"document_id"`
	RequestedBy     string          `json:"requested_by"`
	IdempotencyKey  string          `json:"idempotency_key"`
	Document        ingestDocument  `json:"document"`
	Chunking        ingestChunking  `json:"chunking"`
	Embedding       ingestEmbedding `json:"embedding"`
}

type ingestDocument struct {
	Title     string       `json:"title"`
	FileName  string       `json:"file_name"`
	MimeType  string       `json:"mime_type"`
	SizeBytes int64        `json:"size_bytes"`
	SHA256    string       `json:"sha256"`
	Language  string       `json:"language"`
	Source    ingestSource `json:"source"`
}

type ingestSource struct {
	Type string `json:"type"`
	URI  string `json:"uri"`
}

type ingestChunking struct {
	Strategy        string `json:"strategy"`
	ParentChunkSize int    `json:"parent_chunk_size"`
	ChildChunkSize  int    `json:"child_chunk_size"`
	ChildOverlap    int    `json:"child_overlap"`
	MinChunkSize    int    `json:"min_chunk_size"`
	Splitter        string `json:"splitter"`
	KeepTableIntact bool   `json:"keep_table_intact"`
}

type ingestEmbedding struct {
	Model      string `json:"model"`
	Dimensions int    `json:"dimensions"`
	BatchSize  int    `json:"batch_size"`
	Normalize  bool   `json:"normalize"`
}
