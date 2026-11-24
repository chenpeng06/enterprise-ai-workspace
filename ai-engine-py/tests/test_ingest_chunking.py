"""PDF 分块纯函数测试（不访问数据库/外部 API）。"""

from __future__ import annotations

from app.services.ingest import _chunk_pages


def test_chunk_pages_keeps_parent_child_relationship() -> None:
    pages = [
        (1, "灰度发布规范。" * 40),
        (2, "回滚处置流程。" * 40),
        (3, "演练要求。" * 40),
    ]
    parents = _chunk_pages(
        pages,
        parent_size=240,
        child_size=100,
        overlap=20,
        min_size=20,
    )
    assert parents
    for parent in parents:
        assert parent.page_from >= 1
        assert parent.page_to >= parent.page_from
        assert parent.content
        assert parent.children
        for child in parent.children:
            assert child.content
            assert child.page_no >= 1
            assert child.char_end >= child.char_start
            assert child.token_count >= 1


def test_chunk_pages_small_document() -> None:
    parents = _chunk_pages(
        [(1, "只有一小段规范内容，用于验证短文档不会丢失。")],
        parent_size=1200,
        child_size=300,
        overlap=50,
        min_size=20,
    )
    assert len(parents) == 1
    assert len(parents[0].children) == 1
    assert "规范内容" in parents[0].children[0].content


def test_chunk_pages_empty_input() -> None:
    assert _chunk_pages([], parent_size=1200, child_size=300, overlap=50, min_size=20) == []
