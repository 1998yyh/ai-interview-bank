"""Import public interview practice material and rebuild the portable question bank."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from html import escape
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from study import normalized, organize


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "site" / "index.html"
SITE = ROOT / "dist" / "index.html"
DATA = ROOT / "data" / "questions.json"
USER_AGENT = "AIInterviewBank/1.0"
TOPICS = ("llm", "rag", "agent", "eval", "deploy")
HEADINGS = {
    "anchored": re.compile(
        r'^<a id="(?P<anchor>[a-z0-9-]+-\d+)"></a>[ \t]*\n+'
        r"### \d+[.、][ \t]+(?P<title>[^\n]+)$", re.M | re.I
    ),
    "numbered": re.compile(r"^#{2,4} Q\d+[.：:、][ \t]*(?P<title>[^\n]+)$", re.M | re.I),
    "handbook": re.compile(r"^### (?P<section>[A-K])\d+\.[ \t]*(?P<title>[^\n]+)$", re.M),
}
JSON_ELEMENT = re.compile(r'(<script type="application/json" id="bank-data">).*?(</script>)', re.S)
FENCE = re.compile(r"^[ \t]{0,3}(?P<marker>" + chr(96) + r"{3,}|~{3,})")
ANSWER_MARKDOWN = MarkdownIt("js-default")


def render_answer_link(renderer, tokens, index, options, env):
    token = tokens[index]
    try:
        target = urljoin(env["source_url"], token.attrGet("href") or "")
        url = urlsplit(target)
    except ValueError:
        url = None
    if url and url.scheme in ("https", "http") and url.hostname:
        token.attrSet("href", target)
        token.attrSet("target", "_blank")
        token.attrSet("rel", "noopener noreferrer")
    else:
        token.attrs.pop("href", None)
    return renderer.renderToken(tokens, index, options, env)


def render_answer_image(renderer, tokens, index, options, env):
    return escape(renderer.renderInlineAsText(tokens[index].children, options, env))


def render_table_open(renderer, tokens, index, options, env):
    return '<div class="answer-table-scroll" role="region" aria-label="答案表格" tabindex="0">' + renderer.renderToken(tokens, index, options, env)


def render_table_close(renderer, tokens, index, options, env):
    return renderer.renderToken(tokens, index, options, env) + "</div>\n"


ANSWER_MARKDOWN.add_render_rule("link_open", render_answer_link)
ANSWER_MARKDOWN.add_render_rule("image", render_answer_image)
ANSWER_MARKDOWN.add_render_rule("table_open", render_table_open)
ANSWER_MARKDOWN.add_render_rule("table_close", render_table_close)


def render_answer(text, source_url):
    return ANSWER_MARKDOWN.render(text, {"source_url": source_url})


def reference(label, url):
    if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
        raise ValueError(f"Invalid source URL: {url}")
    return {"label": label, "url": url}


def masked_markdown(text):
    """Hide fenced examples while keeping their character and line offsets."""
    lines = []
    fence = ""
    for line in text.splitlines(keepends=True):
        marker = FENCE.match(line)
        if fence or marker:
            lines.append(" " * len(line.rstrip("\n")) + ("\n" if line.endswith("\n") else ""))
            if not fence:
                fence = marker["marker"]
            elif marker and marker["marker"].startswith(fence) and not line[marker.end():].strip():
                fence = ""
        else:
            lines.append(line)
    return "".join(lines)


def parse_questions(markdown, style, topic, url, label="开放题库", sections=None):
    markdown = markdown.replace("\r\n", "\n")
    masked = masked_markdown(markdown)
    matches = list(HEADINGS[style].finditer(masked))
    records = []
    for index, entry in enumerate(matches):
        record_topic = sections.get(entry["section"]) if sections else topic
        if record_topic not in TOPICS:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        boundary = re.search(r"^#{1,2} [^\n]*$|^<a id=", masked[entry.end():end], re.M)
        if boundary:
            end = entry.end() + boundary.start()
        answer = markdown[entry.end():end].strip()
        answer = re.sub(r"^\s*\*\*(?:答|答案)[：:]\*\*[ \t]*", "", answer).strip()
        answer = re.sub(r"^\s*\*\*难度[：:][^*]+\*\*\s*", "", answer).strip()
        answer = re.sub(r"\n[ \t]*---+[ \t]*$", "", answer).strip()
        if re.fullmatch(r"(?:暂无答案|待补充|TODO|TBD|---)?[。.]?", answer, re.I):
            answer = ""
        title = re.sub(r"^⭐+\s*|\s*⭐+$", "", entry["title"].strip()).strip()
        title = re.sub(r"[（(][^（）()]{0,30}(?:[一二三]面|终面|初级|中级|高级)[）)]$", "", title).strip()
        if not title:
            continue
        position = entry.groupdict().get("anchor")
        if position:
            target = f"{url}#{position}"
        else:
            line = markdown.count("\n", 0, entry.start()) + 1
            target = f"{url}?plain=1#L{line}"
        source = reference(label, target)
        records.append({
            "question": title, "topic": record_topic, "answer": answer,
            "answer_kind": "source" if answer else "pending",
            "origins": [source], "references": [source] if answer else [],
        })
    return records


def merge_questions(records):
    rank = {"pending": 0, "source": 1, "editorial": 2}
    merged = {}
    for entry in records:
        key = normalized(entry["question"])
        if not key:
            continue
        previous = merged.get(key)
        if previous is None:
            merged[key] = {**entry, "id": hashlib.sha256(key.encode()).hexdigest()[:20]}
            continue
        winner = entry if rank[entry["answer_kind"]] > rank[previous["answer_kind"]] else previous
        origins = {source["url"]: source for source in previous["origins"] + entry["origins"]}
        merged[key] = {**winner, "id": previous["id"], "origins": list(origins.values())}
    return list(merged.values())


def download(url, max_bytes):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=14) as response:
        if urlsplit(response.geturl()).scheme != "https":
            raise ValueError(f"Insecure redirect from {url}")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"Response exceeds limit: {url}")
    return body


def collect_archive(source):
    repo = source["repo"]
    revision = source["revision"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Invalid repository or commit: {repo}")
    repo_url = f"https://github.com/{repo}"
    archive_url = f"https://codeload.github.com/{repo}/zip/{revision}"
    records = []
    with ZipFile(BytesIO(download(archive_url, 24 * 1024 * 1024))) as archive:
        prefix = archive.namelist()[0].partition("/")[0] + "/"
        license_file = archive.getinfo(prefix + "LICENSE")
        if license_file.file_size > 16_384:
            raise ValueError(f"Unexpected license size: {repo}")
        license_text = archive.read(license_file).decode("utf-8-sig").strip()
        if not license_text.startswith("MIT License") or "Permission is hereby granted" not in license_text:
            raise ValueError(f"Expected MIT license in {repo} at {revision}")
        for entry in archive.infolist():
            path = entry.filename.removeprefix(prefix)
            if not path.endswith(".md") or PurePosixPath(path).name.lower() in ("readme.md", "references.md"):
                continue
            topic = next((value for pattern, value in source["paths"] if path.startswith(pattern)), None)
            if not topic:
                continue
            if entry.file_size > 2 * 1024 * 1024:
                raise ValueError(f"Unexpected document size: {repo}/{path}")
            records.extend(parse_questions(
                archive.read(entry).decode("utf-8-sig"), source["style"], topic,
                f"{repo_url}/blob/{revision}/{quote(path)}", repo,
                source.get("sections"),
            ))
    if not records:
        raise ValueError(f"No questions extracted from {repo}")
    return {
        "name": repo, "url": f"{repo_url}/tree/{revision}", "revision": revision,
        "count": len(records), "license": license_text,
    }, records


def report_text(html, post_id):
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find(id=post_id)
    if article is None and soup.select_one(".main-content-container h1"):
        article = soup.select_one(".main-content-container .feed-content-text")
    return article.get_text("\n", strip=True) if article else ""


def collect_reports(posts):
    records, results = [], []
    robots_url = "https://www.nowcoder.com/robots.txt"
    rules = RobotFileParser(robots_url)
    try:
        rules.parse(download(robots_url, 128 * 1024).decode("utf-8").splitlines())
    except (OSError, ValueError) as error:
        print(f"Could not read robots.txt, using only previously verified posts: {error}", file=sys.stderr)

    def collect_post(post):
        source = reference(post["label"], post["url"])
        post_path = urlsplit(post["url"])
        if post_path.hostname != "www.nowcoder.com" or not re.fullmatch(r"/feed/main/detail/[0-9a-f]{32}", post_path.path):
            raise ValueError(f"Unsupported interview URL: {post['url']}")
        body = ""
        if rules.can_fetch(USER_AGENT, post["url"]):
            try:
                page = download(post["url"], 2 * 1024 * 1024).decode("utf-8")
                body = normalized(report_text(page, "feed-dynamic-content-" + post_path.path.rsplit("/", 1)[-1]))
            except (OSError, ValueError) as error:
                print(f"{post['label']}: {error}", file=sys.stderr)

        collected = []
        checked = 0
        for item in post["questions"]:
            matched = bool(body) and all(normalized(term) in body for term in item["match"])
            if matched:
                checked += 1
            elif body or not post.get("verified_on"):
                continue
            collected.append({
                "question": item["question"], "topic": item["topic"], "answer": item["answer"],
                "answer_kind": "editorial", "origins": [{**source, "verified": "live" if matched else post["verified_on"]}],
                "references": [reference(label, url) for label, url in item["references"]],
            })
        return {
            "name": post["label"], "url": post["url"], "count": len(collected),
            "live": checked, "previously_verified": len(collected) - checked,
            "skipped": len(post["questions"]) - len(collected),
        }, collected

    for post in posts:
        result, collected = collect_post(post)
        results.append(result)
        records.extend(collected)
    return results, records


def embed_data(html, dataset):
    payload = json.dumps(dataset, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    updated, count = JSON_ELEMENT.subn(lambda match: match[1] + payload + match[2], html)
    if count != 1:
        raise ValueError("Expected one embedded dataset in the HTML")
    return updated


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as staged:
        temp = Path(staged.name)
        staged.write(text)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def collect(config):
    with ThreadPoolExecutor(max_workers=4) as pool:
        archives = list(pool.map(collect_archive, config["archives"]))
    report_sources, editorial = collect_reports(config["reports"])
    sources = [source for source, _ in archives] + report_sources
    records = merge_questions(editorial + [entry for _, entries in archives for entry in entries])
    for record in records:
        answer = config.get("answers", {}).get(record["id"])
        if answer:
            references = [reference(label, url) for label, url in answer["references"]]
            if not answer["text"].strip() or not references:
                raise ValueError(f"Editorial answer needs text and evidence: {record['id']}")
            record.update(answer=answer["text"], answer_kind="editorial", references=references)
    year_month_day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    return {"collected_on": year_month_day, "sources": sources, "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_mutually_exclusive_group()
    stages.add_argument("--render-only", action="store_true", help="Rebuild HTML from the saved dataset without network requests.")
    stages.add_argument("--collect-only", action="store_true", help="Refresh the dataset without changing the HTML.")
    stages.add_argument("--regroup", action="store_true", help="Apply study groups to the saved dataset and rebuild the HTML offline.")
    options = parser.parse_args()
    if options.render_only or options.regroup:
        dataset = json.loads(DATA.read_text(encoding="utf-8"))
    else:
        config = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        dataset = collect(config)

    rules = json.loads((ROOT / "study_topics.json").read_text(encoding="utf-8"))
    dataset = organize(dataset, rules)
    if not options.collect_only:
        page_records = [
            {**row, "answer_html": render_answer(row["answer"], row["origins"][0]["url"])}
            for row in dataset["records"]
        ]
        updated_html = embed_data(TEMPLATE.read_text(encoding="utf-8"), {**dataset, "records": page_records})
    if not options.render_only:
        write_text(DATA, json.dumps(dataset, ensure_ascii=False, indent=2) + "\n")
    if not options.collect_only:
        write_text(SITE, updated_html)

    for source in dataset["sources"]:
        print(f"{source['name']}: {source['count']}")
        if "live" in source:
            print(f"  live={source['live']} previous={source['previously_verified']} skipped={source['skipped']}")
    print(f"Unique questions: {len(dataset['records'])}")
    print(f"Topics: {dict(Counter(record['topic'] for record in dataset['records']))}")
    print(f"Answers: {dict(Counter(record['answer_kind'] for record in dataset['records']))}")
    print(f"Study groups: {len(dataset['study_groups'])}")


if __name__ == "__main__":
    main()
