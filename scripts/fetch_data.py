# -*- coding: utf-8 -*-
"""
우아전시공연 수집기 — 한국문화정보원 한눈에보는문화정보조회서비스 (data.go.kr 15138937, apis.data.go.kr/B553457/cultureinfo)

1) period2 로 오늘~+400일 사이 진행 중·예정인 공연/전시(A)·행사/축제(B)·교육/체험(C) 목록을 받아 data/list.json.gz 에 저장.
2) 처음 보는 일련번호(seq)만 detail2 로 상세(가격·예매 URL·문의·주소)를 받아 data/details/{seq//2000}.json.gz 에 누적.
   목록에서 사라진(종료된) 항목은 캐시에서 제거. 하루 호출 예산(기본 800)만큼만 받고 멈춘다.
3) 초당 제한(코드 23)은 0.5초 간격 + 15초 대기 재시도, 일일 한도(코드 22)는 저장하고 종료.
   응답 문자열이 이중 이스케이프(&amp;lt;)라 빌드에서 unescape 한다.
키: 환경변수 API_KEY → DATA_GO_KR_API_KEY → 로컬 ../hosppass/.env 의 API_KEY.
사용: python scripts/fetch_data.py [--budget N]
"""
import gzip, json, os, re, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DET = DATA / "details"
DET.mkdir(parents=True, exist_ok=True)
BASE = "https://apis.data.go.kr/B553457/cultureinfo/"
BAD = {c for c in range(0, 32) if c not in (9, 10, 13)} | {0xFFFE, 0xFFFF}
GAP = 0.5
BUCKET = 2000
CALLS = 0


class DailyLimit(Exception):
    pass


def api_key():
    for name in ("API_KEY", "DATA_GO_KR_API_KEY"):
        if os.environ.get(name):
            return os.environ[name].strip()
    for p in (ROOT / ".env", ROOT.parent / "hosppass" / ".env"):
        if p.exists():
            m = re.search(r"^API_KEY\s*=\s*(\S+)", p.read_text(encoding="utf-8"), re.M)
            if m:
                return m.group(1).strip("\"'")
    sys.exit("환경변수 API_KEY 가 필요합니다.")


KEY = api_key()
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"


def clean(t):
    return "".join(ch for ch in t if ord(ch) not in BAD)


def call(op, **params):
    global CALLS
    last = ""
    for attempt in range(8):
        try:
            CALLS += 1
            r = S.get(BASE + op, params=dict(serviceKey=KEY, **params), timeout=90)
            txt = clean(r.content.decode("utf-8", "replace"))
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND" in txt or "<returnReasonCode>23<" in txt:
                last = "rate"
                time.sleep(15 + 5 * attempt)
                continue
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS" in txt or "<returnReasonCode>22<" in txt:
                raise DailyLimit(txt[:200])
            root = ET.fromstring(txt.encode("utf-8"))
            if root.tag == "OpenAPI_ServiceResponse":
                raise RuntimeError(txt[:300])
            if root.findtext("./header/resultCode") != "00":
                raise RuntimeError(root.findtext("./header/resultMsg"))
            return root.find("./body") if root.find("./body") is not None else root
        except (requests.RequestException, ET.ParseError) as e:
            last = str(e)
            time.sleep(3 + 3 * attempt)
    raise RuntimeError("API 실패: %s %s" % (op, last))


def rows(body):
    return [{c.tag: (c.text or "").strip() for c in it} for it in body.findall("./items/item")]


def kst_today():
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date()


def fetch_list():
    t0 = kst_today()
    frm, to = t0.strftime("%Y%m%d"), (t0 + timedelta(days=400)).strftime("%Y%m%d")
    out, seen = [], set()
    for tp in ("A", "B", "C"):
        page, n = 1, 1000
        while True:
            body = call("period2", PageNo=page, numOfrows=n, serviceTp=tp, **{"from": frm, "to": to})
            items = rows(body)
            for x in items:
                if x["seq"] not in seen:
                    seen.add(x["seq"])
                    x["svcTp"] = tp
                    out.append(x)
            total = int(body.findtext("totalCount") or 0)
            print("  목록 %s %d/%d" % (tp, min(page * n, total), total), flush=True)
            if page * n >= total:
                break
            page += 1
            time.sleep(GAP)
    return out


def bucket_of(seq):
    return int(seq) // BUCKET


def load_details():
    det = {}
    for p in DET.glob("*.json.gz"):
        det.update(json.loads(gzip.open(p, "rt", encoding="utf-8").read()))
    return det


def save_details(det):
    byb = {}
    for k, d in det.items():
        byb.setdefault(bucket_of(k), {})[k] = d
    keep = set()
    for b, items in byb.items():
        p = DET / ("%d.json.gz" % b)
        keep.add(p.name)
        blob = json.dumps(items, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if p.exists() and gzip.decompress(p.read_bytes()) == blob:
            continue
        with gzip.GzipFile(p, "wb", compresslevel=9, mtime=0) as f:
            f.write(blob)
    for p in DET.glob("*.json.gz"):
        if p.name not in keep:
            p.unlink()


def main():
    budget = int(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else int(os.environ.get("DAILY_BUDGET", "800"))
    lst = fetch_list()
    # 직전 목록 대비 급감하면(90% 미만) 중단 — 빈 데이터로 사이트가 덮이지 않게
    lp = DATA / "list.json.gz"
    if lp.exists():
        prev = len(json.loads(gzip.open(lp, "rt", encoding="utf-8").read()))
        if prev > 100 and len(lst) < prev * 0.6:
            sys.exit("목록이 직전(%d)보다 크게 줄어(%d) 중단" % (prev, len(lst)))
    with gzip.open(lp, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(lst, f, ensure_ascii=False, separators=(",", ":"))
    ids = {x["seq"]: x for x in lst}
    print("현재 목록", len(lst), "건")
    det = load_details()
    n0 = len(det)
    det = {k: v for k, v in det.items() if k in ids}
    print("캐시 상세", n0, "→ 유지", len(det))
    todo = [i for i in ids if i not in det]
    todo.sort(key=lambda i: (ids[i].get("startDate", ""), i))  # 곧 시작하는 것부터
    todo = todo[:max(0, budget - CALLS)]
    print("이번에 받을 상세 %d건 (예산 %d, 지금까지 호출 %d)" % (len(todo), budget, CALLS), flush=True)
    done = fail = 0
    try:
        for n, no in enumerate(todo, 1):
            try:
                r = rows(call("detail2", seq=no))
                if r:
                    det[no] = r[0]
                    done += 1
            except DailyLimit:
                raise
            except Exception as e:
                fail += 1
                print("  실패", no, str(e)[:80])
                if fail > 40:
                    print("실패 과다, 중단")
                    break
            if n % 200 == 0:
                save_details(det)
                print("  상세 %d/%d 실패 %d" % (n, len(todo), fail), flush=True)
            time.sleep(GAP)
    except DailyLimit as e:
        print("일일 호출 한도 도달 — 저장하고 종료:", str(e)[:80].replace(chr(10), " "))
    save_details(det)
    print("완료: 목록 %d, 상세 보유 %d, 이번 신규 %d (실패 %d)" % (len(lst), len(det), done, fail))


if __name__ == "__main__":
    main()
