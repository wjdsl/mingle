#!/usr/bin/env python3
"""밍글 SRS 기반 대시보드 JSON 정적 검증(표준 라이브러리만 사용).

실행 예: python data/dashboard/validate_dashboard_data.py
         python data/dashboard/validate_dashboard_data.py --root /path/to/mingle-main

* DB 접속, API 호출, 실제 통계 정확성 검증은 하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def read_json(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def at_pointer(root, path: str):
    """RFC6901 스타일 경로(/a/b). 이 프로젝트의 검증은 배열 인덱스가 불필요함."""
    if path == "":
        return root
    if not path.startswith("/"):
        raise ValueError(f"잘못된 JSON 포인터: {path}")
    current = root
    for item in path.split("/")[1:]:
        key = item.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(key)]
        else:
            current = current[key]
    return current


def is_subset(expected, actual):
    """객체 일부 항목만 지정해도 해당 객체가 포함되어 있는지 확인한다."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(k in actual and is_subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(is_subset(x, y) for x, y in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def check(rule: dict, doc):
    actual = at_pointer(doc, rule["경로"])
    expected = rule["기대_값"]
    op = rule["검증"]
    if op == "count":
        return hasattr(actual, "__len__") and len(actual) == expected
    if op == "equals":
        return actual == expected and type(actual) is type(expected)
    if op == "not_contains":
        if not isinstance(actual, list):
            raise ValueError("not_contains는 배열만 지원")
        return not any(is_subset(expected, item) for item in actual)
    raise ValueError(f"지원하지 않는 검사 방식: {op}")


def main():
    parser = argparse.ArgumentParser(description="푸르마 대시보드 JSON 19개 정적 검증")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="프로젝트 루트")
    args = parser.parse_args()
    directory = args.root / "data" / "dashboard"
    required = ["pruma_dashboard_event_schema.json", "pruma_dashboard_metrics.json", "pruma_dashboard_tests.json"]
    try:
        docs = {name: read_json(directory / name) for name in required}
        rules = docs[required[2]]["검증_항목"]
        if len(rules) != 19 or len({r["id"] for r in rules}) != 19:
            raise ValueError("검증 항목이 19개가 아니거나 ID가 중복됨")
        if len({x["key"] for x in docs[required[0]]["이벤트_필드"]}) != 7:
            raise ValueError("이벤트 필드 중복 또는 7개 미충족")
        if len({x["이름"] for x in docs[required[1]]["지표"]}) != 10:
            raise ValueError("통계 지표 중복 또는 10개 미충족")
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        print(f"[오류] 파일 로드/기본 검사 실패: {exc}")
        return 1
    failed = 0
    for rule in rules:
        try:
            target = rule["대상_파일"]
            if target not in docs:
                raise ValueError(f"검증 대상 파일 불일치: {target}")
            ok = check(rule, docs[target])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            ok = False
            print(f"[{rule['id']}] 오류: {exc}")
        print(f"[{'통과' if ok else '실패'}] {rule['id']} {rule['검증']} {rule['경로']}")
        if not ok:
            failed += 1
    print(f"\n정적 검사: {len(rules)-failed}/{len(rules)} 통과")
    print("주의: DB 연동·실제 이벤트·운영 보안 테스트를 의미하지 않습니다.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
