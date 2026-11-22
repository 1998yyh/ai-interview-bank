import json
import unittest

from collect import embed_data, merge_questions, parse_questions, render_answer, report_text


class CollectorTests(unittest.TestCase):
    def test_anchored_bank_keeps_real_questions_and_skips_numbered_examples(self):
        markdown = """<a id="rag-001"></a>
### 1. 何时使用混合检索？

从词项匹配和语义检索分别召回候选。

~~~text
<a id="rag-999"></a>
### 2. 示例代码中的标题
~~~
"""
        records = parse_questions(markdown, "anchored", "rag", "https://example.org/source")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["question"], "何时使用混合检索？")
        self.assertEqual(records[0]["origins"][0]["url"], "https://example.org/source#rag-001")

    def test_numbered_bank_preserves_unanswered_questions_for_review(self):
        records = parse_questions("### Q8: 什么是批处理？\n\n---\n", "numbered", "deploy", "https://example.org/source")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["answer_kind"], "pending")

    def test_deduplication_keeps_both_origins_and_uses_editorial_answer(self):
        bank = parse_questions("### Q1: 什么是 RAG？\n\n把检索结果提供给模型。\n", "numbered", "rag", "https://example.org/bank")[0]
        editorial = {**bank, "question": "什么是ＲＡＧ?", "answer": "经核查的回答。",
                     "answer_kind": "editorial", "origins": [{"label": "面经", "url": "https://example.org/post"}]}
        merged = merge_questions([bank, editorial])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["answer"], "经核查的回答。")
        self.assertEqual(len(merged[0]["origins"]), 2)

    def test_report_extraction_skips_comments_and_neighbouring_posts(self):
        document = '<article id="post-a">首个<br>问题？</article><article id="post-b">其他人的评论</article>'
        self.assertEqual(report_text(document, "post-a"), "首个\n问题？")

    def test_untrusted_source_text_cannot_close_embedded_data_element(self):
        shell = '<script type="application/json" id="bank-data">{"records":[]}</script>'
        data = {"records": [{"answer": "</script><script>unexpected()</script>"}]}
        result = embed_data(shell, data)
        self.assertEqual(result.count("</script>"), 1)
        self.assertEqual(json.loads(result.split(">", 1)[1].rsplit("<", 1)[0]), data)

    def test_answer_renders_lists_tables_and_links(self):
        markdown = """- **LangChain** 示例
- LangGraph 示例

| 维度 | LangChain | LangGraph |
| --- | --- | --- |
| 定位 | 高层框架 | 状态化编排 |

[官方文档](https://example.org/docs) 和 [章节](#more)
"""
        rendered = render_answer(markdown, "https://example.org/question#current")
        self.assertIn("<li><strong>LangChain</strong> 示例</li>", rendered)
        self.assertIn("<table>", rendered)
        self.assertIn("<th>LangGraph</th>", rendered)
        self.assertIn("<td>状态化编排</td>", rendered)
        self.assertIn('href="https://example.org/docs"', rendered)
        self.assertIn('href="https://example.org/question#more"', rendered)

    def test_imported_raw_html_and_images_do_not_become_live_elements(self):
        rendered = render_answer(
            '<div>原文中的 HTML</div>\n\n![示例图](https://example.org/image.png)',
            "https://example.org/question",
        )
        self.assertIn("&lt;div&gt;", rendered)
        self.assertIn("示例图", rendered)
        self.assertNotIn("<img", rendered)


if __name__ == "__main__":
    unittest.main()
