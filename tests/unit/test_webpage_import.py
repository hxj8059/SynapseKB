from datetime import UTC, datetime

import pytest
from synapsekb.document_processing.parsers import _parse_html
from synapsekb.document_processing.url_fetcher import webpage_metadata


def test_wechat_metadata_and_article_body_exclude_chrome(tmp_path):
    raw = """<html><head><title>旧标题</title></head><body>
      <h1 id="activity-name">公众号研究文章</h1><p>广告与导航</p>
      <div id="js_content"><h2>产业进展</h2><p>正文内容。</p></div>
      <script>var ct = "1788220800";</script><p>点赞 转发</p></body></html>"""
    title, source_time = webpage_metadata(raw.encode(), "https://mp.weixin.qq.com/s/test")
    assert title == "公众号研究文章"
    assert source_time == datetime.fromtimestamp(1788220800, UTC)
    path = tmp_path / "article.html"
    path.write_text(raw)
    parsed = _parse_html(path)
    assert "正文内容" in parsed.markdown
    assert "点赞" not in parsed.markdown and "广告" not in parsed.markdown


def test_wechat_verification_is_not_imported_as_a_document():
    with pytest.raises(ValueError, match="验证"):
        webpage_metadata(
            "<body>环境异常 请完成验证</body>".encode(),
            "https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha",
        )


def test_other_pages_do_not_infer_publication_from_mentions():
    title, source_time = webpage_metadata(
        b"<title>Report</title><p>2026-07-15 event</p>", "https://example.com/report"
    )
    assert title == "Report" and source_time is None
