import unittest

from study import organize


class StudyGroupsTests(unittest.TestCase):
    def test_groups_every_question_and_keeps_original_data(self):
        questions = [
            self.question("a", "文档怎么切片？", "rag-ingestion.md"),
            self.question("b", "Chunk 如何设置重叠？", "rag-ingestion.md"),
            self.question("c", "如何用 RRF 融合 BM25 与向量检索？", "rag-ingestion.md"),
            self.question("d", "知识库设计有什么注意事项？", "overview.md"),
        ]
        rules = {
            "rag": [
                {"id": "rag-overview", "label": "流程", "summary": "完整链路。"},
                {"id": "rag-chunks", "label": "切片", "summary": "切片和重叠。",
                 "paths": ["rag-ingestion"], "terms": ["切片", "chunk"]},
                {"id": "rag-retrieval", "label": "检索", "summary": "召回和融合。",
                 "terms": ["rrf", "bm25", "向量检索"]},
            ],
        }
        data = organize({"records": questions, "sources": []}, rules)
        self.assertEqual([
            "rag-chunks", "rag-chunks", "rag-retrieval", "rag-overview",
        ], [record["study_group"] for record in data["records"]])
        self.assertTrue(all(
            original == {key: row[key] for key in original}
            for original, row in zip(questions, data["records"])
        ))
        self.assertNotIn("study_group", questions[0])
        self.assertEqual(
            {"rag-overview": 1, "rag-chunks": 2, "rag-retrieval": 1},
            {group["id"]: group["count"] for group in data["study_groups"]},
        )

    @staticmethod
    def question(key, title, source):
        return {
            "id": key, "topic": "rag", "question": title,
            "answer": "用实验验证实现。", "answer_kind": "source",
            "origins": [{"url": f"https://example.org/{source}"}],
        }


if __name__ == "__main__":
    unittest.main()
