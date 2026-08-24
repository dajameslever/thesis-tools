from thesis_tools.review_html import markdown_to_html, render_review_html


def test_headings_become_anchored_sections_and_a_contents_list():
    body, toc = markdown_to_html("# Title\n\n## 1. Does X affect Y?\n\nSome prose.\n")
    assert "<h1>Title</h1>" in body
    assert '<h2 id="1-does-x-affect-y">1. Does X affect Y?</h2>' in body
    assert toc == [("1-does-x-affect-y", "1. Does X affect Y?")]


def test_only_h2_sections_reach_the_contents_list():
    _, toc = markdown_to_html("# Title\n\n## Section\n\n### Subsection\n")
    assert [t for _, t in toc] == ["Section"]


def test_consecutive_lines_join_into_one_paragraph():
    body, _ = markdown_to_html("First line\nsecond line\n\nNew paragraph.\n")
    assert "<p>First line second line</p>" in body
    assert "<p>New paragraph.</p>" in body


def test_blockquote_becomes_a_callout():
    body, _ = markdown_to_html("> Warning text.\n")
    assert '<blockquote class="lr-callout"><p>Warning text.</p></blockquote>' in body


def test_bullets_become_a_list():
    body, _ = markdown_to_html("- one\n- two\n")
    assert body == "<ul><li>one</li><li>two</li></ul>"


def test_inline_emphasis_is_converted():
    body, _ = markdown_to_html("**bold** and *italic* and _also italic_ and `code`\n")
    assert "<strong>bold</strong>" in body
    assert body.count("<em>") == 2
    assert "<code>code</code>" in body


def test_markup_in_content_is_escaped_not_executed():
    body, _ = markdown_to_html("A title with <script>alert(1)</script> & an ampersand\n")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "&amp;" in body


def test_a_paper_title_containing_markup_stays_escaped_in_the_page():
    html = render_review_html("## <img src=x onerror=y>\n\nProse.\n")
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_render_is_a_complete_self_contained_page():
    html = render_review_html("# Literature Review — Draft\n\n## Section\n\nProse.\n")
    assert html.startswith("<!doctype html>")
    assert "<style>" in html          # inlined, no external assets
    assert "http://" not in html and "https://" not in html
    assert "Contents" in html


def test_page_without_sections_still_renders():
    html = render_review_html("# Just a title\n")
    assert "<h1>Just a title</h1>" in html
    assert "Contents" not in html
