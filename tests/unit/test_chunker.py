from synapsekb.document_processing.chunker import HeadingAwareChunker


def test_heading_aware_chunks_preserve_section() -> None:
    markdown = "# 总览\n\n" + ("知识连接。" * 100) + "\n\n## 结论\n\n结论内容"
    chunks = HeadingAwareChunker(target_tokens=80, overlap_tokens=10).split(markdown)
    assert chunks
    assert chunks[0].section == "总览"
    assert any(chunk.section == "结论" for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_chunker_tracks_page_markers_for_citations() -> None:
    chunks = HeadingAwareChunker(target_tokens=20, overlap_tokens=5).split(
        "<!-- page:3 -->\n# 标题\n正文内容。"
    )
    assert chunks
    assert chunks[0].page_from == 3
    assert chunks[0].page_to == 3
    assert "<!-- page:" not in chunks[0].content
