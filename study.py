"""Organize the collected questions into study groups without changing their text."""

from collections import Counter
import re
import unicodedata
from urllib.parse import unquote, urlsplit


def normalized(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def organize(dataset, rules):
    groups = {}
    for topic, definitions in rules.items():
        groups[topic] = []
        for definition in definitions:
            terms = tuple(normalized(term) for term in definition.get("terms", []))
            phrases = tuple(normalized(phrase) for phrase in definition.get("phrases", []))
            paths = tuple(path.casefold() for path in definition.get("paths", []))
            groups[topic].append((definition, terms, phrases, paths))

    records = []
    counts = Counter()
    for record in dataset["records"]:
        question = normalized(record["question"])
        sources = [unquote(urlsplit(source["url"]).path).casefold() for source in record["origins"]]

        def score(group):
            _, terms, phrases, paths = group
            path_match = any(path in source for path in paths for source in sources)
            return (
                5 * path_match
                + 2 * sum(term in question for term in terms)
                + 8 * any(phrase in question for phrase in phrases)
            )

        definition, *_ = max(groups[record["topic"]], key=score)
        group_id = definition["id"]
        records.append({**record, "study_group": group_id})
        counts[group_id] += 1

    study_groups = [
        {
            "id": definition["id"], "topic": topic, "label": definition["label"],
            "summary": definition["summary"], "count": counts[definition["id"]],
        }
        for topic, definitions in rules.items()
        for definition in definitions
        if counts[definition["id"]]
    ]
    return {**dataset, "records": records, "study_groups": study_groups}
