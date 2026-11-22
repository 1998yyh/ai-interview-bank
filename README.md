# 大模型应用开发面试题库

题库从线上获取题目和已有答案，并生成能直接在浏览器打开的单文件 HTML。首页按主题列出全部题型，左侧可展开二级专题。进入专题即可浏览全部题目和参考答案。页面支持搜索、分页及查看来源，正文中的 Markdown 表格、列表和链接可离线显示。

## 本地构建

在此目录用 Python 3.10 或更新版本运行。

```powershell
python -m pip install -r requirements.txt
python collect.py --render-only
```

构建后打开 `dist/index.html`。构建使用已入库的 [JSON 数据](data/questions.json)，并把数据嵌入 HTML，页面可离线使用。

运行 `python collect.py` 可以联网更新题库并重新构建。只更新 JSON 可用 `python collect.py --collect-only`。

## 题型整理

[题型规则](study_topics.json)包含每个专题的名称、复习要点和归类依据。分类参考题干和上游章节。改动规则后可运行 `python collect.py --regroup`，用已保存的题库离线更新 JSON 和页面。

## 来源和答案

- [采集配置](sources.json)记录开放题库、固定提交和主题路径，以及选入的公开面经考点。改动提交号前应核对仓库许可和 Markdown 结构。
- 开放题库的答案标为「来源题库」。脚本保留题目定位、上游许可和版权声明。牛客面经题按原帖考点改写，补写答案附论文或官方文档。
- 去重按题干统一全半角、大小写和标点后匹配，重复记录保留出处。近义题可能仍然并存。
- `answer_kind` 为 `pending` 的记录需要补答。用 JSON 中的题目 `id` 在 `sources.json` 的 `answers` 对象中登记答案文本和依据，再次采集后会带入页面。

```json
{
  "answers": {
    "题目的 id": {
      "text": "参考答案",
      "references": [["论文或官方文档标题", "https://example.org/reference"]]
    }
  }
}
```

牛客正文当次不可读时，已核对过的配置记录仍带原帖链接，脚本会报告本次直接核对和沿用先前记录的数量。任一开放题库下载或许可校验失败时，脚本保留上一版数据。

## 采集器测试

```powershell
python -m unittest discover
```

## GitHub Actions 部署

GitHub Pages 的发布源设为 GitHub Actions。推送到 `main` 会触发流水线，也可以在 Actions 页手动运行。流水线先测试，再用仓库内的题库快照构建页面，并把 `dist/` 部署到 GitHub Pages。
