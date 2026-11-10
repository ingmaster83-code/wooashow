# -*- coding: utf-8 -*-
"""우아전시공연 정적 사이트 생성기.
입력: data/list.json.gz(진행 중·예정 목록) · data/details/*.json.gz(상세 캐시: 가격·예매 URL·문의·주소)
출력: _site/  (행사 상세, 종류·지역·장소 허브, 무료, 이번 주말, 곧 끝나는, 월별, 안내, 검색 인덱스, sitemap)
상세가 아직 없는 행사는 목록(제목·기간·장소)에만 나오고 상세 페이지는 만들지 않는다 — 상세는 매일 예산만큼 쌓인다.
"""
import collections, gzip, hashlib, html as ihtml, json, re, shutil, sys
from datetime import datetime, timedelta, timezone

from common import *  # noqa

sys.stdout.reconfigure(encoding="utf-8")
DATA = ROOT / "data"
TODAY = (datetime.now(timezone.utc) + timedelta(hours=9)).date()

AREA = {"서울시": "서울", "서울특별시": "서울", "경기도": "경기", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
        "울산광역시": "울산", "세종특별자치시": "세종", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
        "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주"}
LONG = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
        "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도", "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
        "제주": "제주특별자치도", "전남광주통합": "전남광주통합특별시"}
REALMS = ["음악/콘서트", "전시", "연극", "뮤지컬/오페라", "무용/발레", "국악", "아동/가족", "행사/축제", "교육/체험", "기타"]
REALM_SLUG = {r: r.replace("/", "·") for r in REALMS}
WD = "월화수목금토일"


def un(s):
    for _ in range(2):
        s = ihtml.unescape(s or "")
    return s.strip()


def todate(d):
    try:
        return datetime.strptime(d, "%Y%m%d").date()
    except Exception:
        return None


def ymd(d):
    d = (d or "").strip()
    return "%s.%s.%s" % (d[:4], d[4:6], d[6:8]) if re.fullmatch(r"\d{8}", d) else ""


def period(a, b):
    a, b = ymd(a), ymd(b)
    return a if a == b else ("%s ~ %s" % (a, b) if a and b else (a or b))


def phone_ok(p):
    return re.sub(r"\s+", " ", p or "").strip()


def text_block(t, cap=1400):
    t = re.sub(r"[ \t]+", " ", (t or "").replace("\r", "")).strip()
    t = re.sub(r"\n\s*\n+", "\n", t)
    if len(t) > cap:
        t = t[:cap].rsplit("\n", 1)[0].rsplit(" ", 1)[0] + " …"
    return "<br>".join(esc(l.strip()) for l in t.split("\n") if l.strip())


# ───────────────────────── 데이터 ─────────────────────────
def load():
    lst = json.loads(gzip.open(DATA / "list.json.gz", "rt", encoding="utf-8").read())
    det = {}
    for p in (DATA / "details").glob("*.json.gz"):
        det.update(json.loads(gzip.open(p, "rt", encoding="utf-8").read()))
    ev = []
    for x in lst:
        s, e = todate(x.get("startDate")), todate(x.get("endDate"))
        if not s or not e or e < TODAY:
            continue
        d = {k: un(v) for k, v in (det.get(x["seq"]) or {}).items()} if det.get(x["seq"]) else None
        realm = x.get("realmName") or ("교육/체험" if x["svcTp"] == "C" else "기타")
        if realm not in REALMS:
            realm = "기타"
        area = AREA.get(x.get("area", ""), x.get("area", ""))
        p = dict(seq=x["seq"], title=un(x.get("title")), s=s, e=e, sd=x["startDate"], ed=x["endDate"], place=un(x.get("place")), realm=realm, svc=x.get("serviceName", ""),
                 area=area, sgg=un(x.get("sigungu")), d=d)
        p["free"] = bool(d and "무료" in (d.get("price") or ""))
        p["perm"] = (e - s).days > 365
        p["venue"] = ""
        if d:
            p["venue"] = d.get("placeSeq") or ""
        if not p["venue"] and p["place"]:
            p["venue"] = "n" + hashlib.md5((p["place"] + p["area"]).encode()).hexdigest()[:8]
        ev.append(p)
    return ev


def rg(p):
    return (p["area"] + " " + p["sgg"]).strip() or "지역 미상"


def state(p):
    if p["s"] > TODAY:
        return "예정"
    return "진행 중"


def link(p):
    return '<a href="/event/%s/">%s</a>' % (p["seq"], esc(p["title"])) if p["d"] else esc(p["title"])


def etable(L, cap=200, region=True):
    L = L[:cap]
    head = "<tr><th>공연·전시</th><th>분야</th><th>장소</th>%s<th>기간</th><th>비고</th></tr>" % ("<th>지역</th>" if region else "")
    rows = []
    for p in L:
        tags = []
        if p["free"]:
            tags.append('<span class="tag gil">무료</span>')
        if p["s"] > TODAY:
            tags.append('<span class="tag term">예정</span>')
        left = (p["e"] - TODAY).days
        if p["perm"]:
            tags.append('<span class="tag">장기</span>')
        elif 0 <= left <= 7:
            tags.append('<span class="tag hol">D-%d</span>' % left)
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td>%s<td>%s</td><td>%s</td></tr>" % (
            link(p), esc(p["realm"]), esc(p["place"] or "-"), ("<td>%s</td>" % esc(rg(p))) if region else "", esc(period(p["sd"], p["ed"])), " ".join(tags)))
    return '<div class="tbl-wrap"><table class="tbl">%s%s</table></div>' % (head, "".join(rows))


def keyd(p):
    return (p["d"] is None, p["e"], p["seq"])


def stat(L):
    n = len(L)
    f = sum(1 for p in L if p["free"])
    r = collections.Counter(p["realm"] for p in L).most_common(3)
    s = "현재 진행 중이거나 예정인 공연·전시·행사 <b>%d건</b>입니다." % n
    if r:
        s += " " + ", ".join("%s %d건" % (a, b) for a, b in r) + " 순으로 많습니다."
    if f:
        s += " 이 중 무료로 확인된 행사는 %d건입니다." % f
    return '<p class="lead">%s</p>' % s


# ───────────────────────── 페이지 ─────────────────────────
def page_event(p, by_venue, hubs_ok):
    d = p["d"]
    addr = d.get("placeAddr") or ""
    price = d.get("price") or ""
    lead = ["<b>%s</b>은(는) %s의 <b>%s</b>에서 열리는 %s입니다." % (esc(p["title"]), esc(rg(p)), esc(p["place"] or "공연장·전시장 미상"), esc(p["realm"]))]
    lead.append("기간은 %s%s이며 현재 <b>%s</b>입니다." % (esc(period(p["sd"], p["ed"])), "(장기 상연·전시)" if p["perm"] else "", state(p)))
    if p["free"]:
        lead.append("무료로 안내돼 있습니다.")
    elif price:
        lead.append("요금은 %s입니다." % esc(price))
    left = (p["e"] - TODAY).days
    if 0 <= left <= 14 and not p["perm"]:
        lead.append("종료까지 %d일 남았습니다." % left)
    rows = [("분야", p["realm"]), ("기간", period(p["sd"], p["ed"])), ("상태", state(p)), ("장소", p["place"]), ("주소", addr), ("지역", rg(p)),
            ("요금", price), ("문의", phone_ok(d.get("phone")))]
    tbl = '<div class="tbl-wrap"><table class="tbl">%s</table></div>' % "".join("<tr><th>%s</th><td>%s</td></tr>" % (a, esc(b)) for a, b in rows if b)
    body = ['<div class="page-head"><h1>%s</h1><p>%s · %s</p></div>' % (esc(p["title"]), esc(p["realm"]), esc(p["place"] or rg(p))), '<p class="lead">%s</p>' % " ".join(lead), ad(),
            '<h2 class="group-title">기본 정보</h2>', tbl]
    if d.get("contents1"):
        body.append('<h2 class="group-title">소개</h2><div class="lead">%s</div>' % text_block(d["contents1"]))
    btns = []
    if d.get("url") and d["url"].startswith("http"):
        btns.append('<a class="btn" href="%s" rel="nofollow noopener" target="_blank">🎟️ 예매·상세 정보</a>' % esc(d["url"]))
    if d.get("placeUrl") and d["placeUrl"].startswith("http"):
        btns.append('<a class="btn" href="%s" rel="nofollow noopener" target="_blank">🏛️ 장소 홈페이지</a>' % esc(d["placeUrl"]))
    if addr:
        btns.append('<a class="btn" href="https://map.kakao.com/?q=%s">🗺️ 지도에서 위치 보기</a>' % urllib.parse.quote(addr))
    if btns:
        body.append("<p>%s</p>" % " ".join(btns))
    body.append('<div class="note-box">일정·요금은 변경될 수 있습니다. 예매 전 예매처와 장소의 최신 안내를 확인하세요. 정보 출처: 한국문화정보원 문화포털(공공데이터포털).</div>')
    sib = [o for o in by_venue.get(p["venue"], []) if o is not p][:8] if p["venue"] else []
    if sib:
        body.append('<h2 class="group-title">같은 장소의 다른 공연·전시 <small>%s</small></h2>' % esc(p["place"]))
        body.append(etable(sib, region=False))
    chips = []
    if p["area"] and ("region", p["area"]) in hubs_ok:
        chips.append('<a class="chip" href="/region/%s/">%s 공연·전시</a>' % (q(p["area"]), esc(p["area"])))
    chips.append('<a class="chip" href="/type/%s/">%s</a>' % (q(REALM_SLUG[p["realm"]]), esc(p["realm"])))
    if p["area"] and ("type", p["realm"], p["area"]) in hubs_ok:
        chips.append('<a class="chip" href="/type/%s/%s/">%s %s</a>' % (q(REALM_SLUG[p["realm"]]), q(p["area"]), esc(p["area"]), esc(p["realm"])))
    if ("venue", p["venue"]) in hubs_ok:
        chips.append('<a class="chip" href="/venue/%s/">%s 전체 일정</a>' % (q(p["venue"]), esc(p["place"])))
    if p["free"]:
        chips.append('<a class="chip" href="/free/">무료 공연·전시</a>')
    body.append('<div class="chips">%s</div>' % "".join(chips))
    faq = [("%s 요금은 얼마인가요?" % p["title"], ("무료로 안내돼 있습니다." if p["free"] else ("등록된 요금 정보는 %s입니다. 좌석·회차에 따라 달라질 수 있으니 예매처에서 확인하세요." % price if price else "등록된 요금 정보가 없습니다. 예매처나 장소에 문의하세요."))),
           ("%s 어디서 예매하나요?" % p["title"], "상단 '예매·상세 정보' 링크 또는 장소 문의처에서 확인할 수 있습니다." if btns else "예매 링크가 등록돼 있지 않습니다. 문의처로 확인하세요."),
           ("공연·전시 기간은 언제인가요?", "%s입니다. 휴관일·회차는 장소에 따라 다르니 방문 전에 확인하세요." % period(p["sd"], p["ed"]))]
    crumbs = [("홈", "/")] + ([(p["area"], "/region/%s/" % p["area"])] if ("region", p["area"]) in hubs_ok else []) + [((p["title"][:28] + "…") if len(p["title"]) > 28 else p["title"], "/event/%s/" % p["seq"])]
    ld = [{"@context": "https://schema.org", "@type": "Event", "name": p["title"], "startDate": "%s-%s-%s" % (p["sd"][:4], p["sd"][4:6], p["sd"][6:8]), "endDate": "%s-%s-%s" % (p["ed"][:4], p["ed"][4:6], p["ed"][6:8]),
           "location": {"@type": "Place", "name": p["place"] or rg(p), **({"address": addr} if addr else {})}, "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode"}]
    title = "%s - %s %s 일정·요금" % (p["title"], p["place"] or rg(p), p["realm"])
    desc = "%s %s %s 일정과 요금 정보: %s, %s." % (rg(p), p["place"], p["realm"], p["title"], period(p["sd"], p["ed"]))
    write("/event/%s/" % p["seq"], layout("/event/%s/" % p["seq"], title, desc.replace("  ", " "), "\n".join(body), faq, crumbs, "article", ld, coupang=True), "0.6")


def hub(path, h1, sub, L, extra="", cap=200, title=None, desc=None, crumbs=None, prio="0.7", region=True, faq=None):
    body = ['<div class="page-head"><h1>%s</h1><p>%s</p></div>' % (esc(h1), esc(sub)), stat(L), ad(), extra, '<h2 class="group-title">일정 목록 <small>종료가 가까운 순</small></h2>', etable(L, cap, region)]
    if len(L) > cap:
        body.append('<p class="note">행사가 많아 %d건만 표시했습니다. 지역·종류별 페이지에서 좁혀 보세요.</p>' % cap)
    write(path, layout(path, title or h1, desc or sub, "\n".join(b for b in body if b), faq, crumbs or [("홈", "/")], coupang=True), prio)


def build():
    ev = load()
    print("행사", len(ev), "상세 보유", sum(1 for p in ev if p["d"]))
    for L in ():
        pass
    ev.sort(key=keyd)
    by_realm, by_area, by_sgg, by_venue = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    by_ra = collections.defaultdict(list)
    for p in ev:
        by_realm[p["realm"]].append(p)
        if p["area"]:
            by_area[p["area"]].append(p)
            by_ra[(p["realm"], p["area"])].append(p)
            if p["sgg"]:
                by_sgg[(p["area"], p["sgg"])].append(p)
        if p["venue"]:
            by_venue[p["venue"]].append(p)
    hubs_ok = set()
    for a, L in by_area.items():
        hubs_ok.add(("region", a))
    for (r, a), L in by_ra.items():
        if len(L) >= 3:
            hubs_ok.add(("type", r, a))
    for v, L in by_venue.items():
        if len(L) >= 2:
            hubs_ok.add(("venue", v))
    # 디렉터리 정리(폴더는 두고 내용만)
    OUT.mkdir(parents=True, exist_ok=True)
    for ch in OUT.iterdir():
        shutil.rmtree(ch) if ch.is_dir() else ch.unlink()
    for p in ev:
        if p["d"]:
            page_event(p, by_venue, hubs_ok)
    # 종류 허브
    for r, L in by_realm.items():
        ac = collections.Counter(p["area"] for p in L if p["area"])
        chips = '<h2 class="group-title">지역별</h2><div class="chips">%s</div>' % "".join(
            ('<a class="chip" href="/type/%s/%s/">%s <small>%d</small></a>' % (q(REALM_SLUG[r]), q(a), esc(a), n)) if ("type", r, a) in hubs_ok else '<span class="chip">%s <small>%d</small></span>' % (esc(a), n) for a, n in ac.most_common())
        hub("/type/%s/" % REALM_SLUG[r], "%s 일정 %d건" % (r, len(L)), "진행 중·예정인 %s" % r, L, chips, 200, "%s 일정·요금 (진행 중 %d건)" % (r, len(L)), "지금 볼 수 있는 %s %d건의 일정·장소·요금을 지역별로 정리했습니다." % (r, len(L)),
            [("홈", "/"), ("종류별", "/type/"), (r, "/type/%s/" % REALM_SLUG[r])], "0.8",
            faq=[("%s 일정은 어디서 확인하나요?" % r, "이 페이지에서 지역을 고르고 행사 상세의 예매 링크로 예매할 수 있습니다."), ("지금 진행 중인 %s는 몇 건인가요?" % r, "오늘 기준 %d건이며 매일 갱신됩니다." % len(L))])
    for (r, a), L in by_ra.items():
        if len(L) >= 3:
            hub("/type/%s/%s/" % (REALM_SLUG[r], a), "%s %s 일정 %d건" % (a, r, len(L)), "%s의 %s" % (LONG.get(a, a), r), L, "", 200, "%s %s 일정 %d건" % (a, r, len(L)), "%s의 %s %d건을 장소·기간·요금과 함께 정리했습니다." % (LONG.get(a, a), r, len(L)),
                [("홈", "/"), (r, "/type/%s/" % REALM_SLUG[r]), (a, "/type/%s/%s/" % (REALM_SLUG[r], a))], "0.6", region=False)
    cards = "".join('<a class="card" href="/type/%s/"><b>%s</b><span>%d건</span></a>' % (q(REALM_SLUG[r]), esc(r), len(by_realm[r])) for r in REALMS if r in by_realm)
    write("/type/", layout("/type/", "종류별 공연·전시 일정", "음악·콘서트, 전시, 연극, 뮤지컬 등 종류별 진행 중인 공연·전시를 찾으세요.", '<div class="page-head"><h1>종류별 공연·전시</h1></div>' + ad() + '<div class="card-grid">%s</div>' % cards, None, [("홈", "/"), ("종류별", "/type/")]), "0.8")
    # 지역 허브
    for a, L in by_area.items():
        sc = collections.Counter(p["sgg"] for p in L if p["sgg"])
        rc = collections.Counter(p["realm"] for p in L)
        extra = '<h2 class="group-title">종류별</h2><div class="chips">%s</div>' % "".join(
            ('<a class="chip" href="/type/%s/%s/">%s <small>%d</small></a>' % (q(REALM_SLUG[r]), q(a), esc(r), n)) if ("type", r, a) in hubs_ok else '<span class="chip">%s <small>%d</small></span>' % (esc(r), n) for r, n in rc.most_common())
        if sc:
            extra += '<h2 class="group-title">시군구별</h2><div class="chips">%s</div>' % "".join(
                ('<a class="chip" href="/region/%s/%s/">%s <small>%d</small></a>' % (q(a), q(g), esc(g), n)) if n >= 3 else '<span class="chip">%s <small>%d</small></span>' % (esc(g), n) for g, n in sc.most_common(60))
        hub("/region/%s/" % a, "%s 공연·전시 %d건" % (LONG.get(a, a), len(L)), "진행 중·예정 일정", L, extra, 200, "%s 공연·전시 일정 %d건" % (a, len(L)), "%s의 공연·전시·행사 %d건을 종류·시군구별로 정리했습니다. 무료 행사와 곧 끝나는 전시도 확인하세요." % (LONG.get(a, a), len(L)),
            [("홈", "/"), ("지역별", "/region/"), (a, "/region/%s/" % a)], "0.8", faq=[("%s에서 지금 볼 수 있는 공연·전시는 몇 건인가요?" % a, "오늘 기준 %d건이며 매일 갱신됩니다." % len(L))])
    for (a, g), L in by_sgg.items():
        if len(L) >= 3:
            hub("/region/%s/%s/" % (a, g), "%s %s 공연·전시 %d건" % (a, g, len(L)), "진행 중·예정 일정", L, "", 200, "%s %s 공연·전시 %d건" % (a, g, len(L)), "%s %s의 공연·전시 %d건을 정리했습니다." % (a, g, len(L)),
                [("홈", "/"), (a, "/region/%s/" % a), (g, "/region/%s/%s/" % (a, g))], "0.6", region=False)
    cards = "".join('<a class="card" href="/region/%s/"><b>%s</b><span>%d건</span></a>' % (q(a), esc(a), len(L)) for a, L in sorted(by_area.items(), key=lambda t: -len(t[1])))
    write("/region/", layout("/region/", "지역별 공연·전시 일정", "시도별로 진행 중인 공연·전시·행사를 확인하세요.", '<div class="page-head"><h1>지역별 공연·전시</h1></div>' + ad() + '<div class="card-grid">%s</div>' % cards, None, [("홈", "/"), ("지역별", "/region/")]), "0.8")
    # 장소 허브
    nv = 0
    vtitles = collections.Counter("%s 공연·전시 일정 (%s, %d건)" % (L[0]["place"] or "장소 미상", rg(L[0]), len(L)) for L in by_venue.values() if len(L) >= 2)
    for v, L in by_venue.items():
        if len(L) >= 2:
            name = L[0]["place"] or "장소 미상"
            vt = "%s 공연·전시 일정 (%s, %d건)" % (name, rg(L[0]), len(L))
            if vtitles[vt] > 1:
                vt = "%s 공연·전시 일정 (%s, %d건, 장소번호 %s)" % (name, rg(L[0]), len(L), v)
            hub("/venue/%s/" % v, "%s 공연·전시 일정 %d건" % (name, len(L)), rg(L[0]), L, "", 100, vt, "%s(%s)에서 열리는 공연·전시 %d건의 일정과 요금을 정리했습니다." % (name, rg(L[0]), len(L)),
                [("홈", "/"), (L[0]["area"] or "지역", ("/region/%s/" % L[0]["area"]) if ("region", L[0]["area"]) in hubs_ok else "/"), (name, "/venue/%s/" % v)], "0.5", region=False)
            nv += 1
    # 무료
    F = [p for p in ev if p["free"]]
    fa = collections.Counter(p["area"] for p in F if p["area"])
    extra = '<h2 class="group-title">지역별</h2><div class="chips">%s</div>' % "".join(('<a class="chip" href="/free/%s/">%s <small>%d</small></a>' % (q(a), esc(a), n)) if n >= 3 else '<span class="chip">%s <small>%d</small></span>' % (esc(a), n) for a, n in fa.most_common())
    hub("/free/", "무료 공연·전시 %d건" % len(F), "요금이 무료로 안내된 진행 중·예정 행사", F, extra, 250, "무료 공연·전시 %d건 - 지역별 무료 관람" % len(F), "무료로 관람할 수 있는 공연·전시·행사 %d건을 지역별로 모았습니다." % len(F), [("홈", "/"), ("무료", "/free/")], "0.9",
        faq=[("무료 공연·전시는 예약이 필요 없나요?", "무료여도 사전 예약이 필요한 경우가 있습니다. 행사 상세의 예매·상세 링크와 문의처에서 확인하세요.")])
    for a, n in fa.items():
        if n >= 3:
            L = [p for p in F if p["area"] == a]
            hub("/free/%s/" % a, "%s 무료 공연·전시 %d건" % (a, len(L)), "무료로 안내된 행사", L, "", 200, "%s 무료 공연·전시 %d건" % (a, len(L)), "%s에서 무료로 관람할 수 있는 공연·전시·행사 %d건입니다." % (LONG.get(a, a), len(L)), [("홈", "/"), ("무료", "/free/"), (a, "/free/%s/" % a)], "0.7", region=False)
    # 이번 주말
    sat = TODAY + timedelta(days=(5 - TODAY.weekday()) % 7)
    if TODAY.weekday() == 6:
        sat = TODAY - timedelta(days=1)
    sun = sat + timedelta(days=1)
    W = [p for p in ev if p["s"] <= sun and p["e"] >= max(sat, TODAY) and not p["perm"]]
    W.sort(key=lambda p: (p["realm"] != "전시", p["e"], p["seq"]))
    hub("/weekend/", "이번 주말(%s~%s) 공연·전시 %d건" % (sat.strftime("%m.%d"), sun.strftime("%m.%d"), len(W)), "주말에 볼 수 있는 일정", W, "", 250, "이번 주말 공연·전시 %d건 (%s~%s)" % (len(W), sat.strftime("%m.%d"), sun.strftime("%m.%d")),
        "이번 주말(%s~%s)에 볼 수 있는 공연·전시·행사 %d건을 모았습니다." % (sat.strftime("%m.%d"), sun.strftime("%m.%d"), len(W)), [("홈", "/"), ("이번 주말", "/weekend/")], "0.9",
        faq=[("이번 주말에 볼 만한 전시는 어디서 확인하나요?", "이 목록은 이번 주말 기간과 겹치는 공연·전시를 기간이 빨리 끝나는 순으로 보여줍니다. 휴관일은 장소에 확인하세요.")])
    # 곧 끝나는
    E = sorted([p for p in ev if 0 <= (p["e"] - TODAY).days <= 14 and not p["perm"] and p["s"] <= TODAY], key=lambda p: (p["e"], p["seq"]))
    hub("/ending/", "곧 끝나는 공연·전시 %d건" % len(E), "2주 안에 종료되는 일정", E, "", 250, "곧 끝나는 공연·전시 %d건 (14일 이내 종료)" % len(E), "14일 안에 종료되는 공연·전시·행사 %d건을 종료일 순으로 정리했습니다." % len(E), [("홈", "/"), ("곧 끝나는", "/ending/")], "0.9")
    # 월별
    for i in range(3):
        y, m = (TODAY.year + (TODAY.month - 1 + i) // 12, (TODAY.month - 1 + i) % 12 + 1)
        a = datetime(y, m, 1).date()
        b = (datetime(y + (m == 12), m % 12 + 1, 1).date() - timedelta(days=1))
        M = [p for p in ev if p["s"] <= b and p["e"] >= a and not p["perm"]]
        M.sort(key=lambda p: (p["realm"] != "전시", p["e"], p["seq"]))
        hub("/month/%04d-%02d/" % (y, m), "%d년 %d월 공연·전시 %d건" % (y, m, len(M)), "%d월에 볼 수 있는 일정" % m, M, "", 250, "%d년 %d월 공연·전시 일정 %d건" % (y, m, len(M)), "%d년 %d월에 열리는 공연·전시·행사 %d건을 정리했습니다." % (y, m, len(M)), [("홈", "/"), ("%d월" % m, "/month/%04d-%02d/" % (y, m))], "0.7")
    # 홈
    new = sorted([p for p in ev if p["s"] <= TODAY], key=lambda p: (-int(p["seq"])))[:10]
    body = ['<div class="hero"><h1>공연·전시 일정 찾기</h1><p>문화포털에 등록된 공연·전시·행사 %s건을 지역·종류·무료 여부로 찾으세요</p>'
            '<div class="today-box"><div><small>진행·예정</small><b>%s건</b></div><div><small>이번 주말</small><b>%d건</b></div><div><small>무료</small><b>%d건</b></div><div><small>장소</small><b>%d곳</b></div></div></div>' % (
                "{:,}".format(len(ev)), "{:,}".format(len(ev)), len(W), len(F), len({p["venue"] for p in ev if p["venue"]})),
            '<div class="search-box"><input id="q" type="search" placeholder="공연·전시 검색 (예: 뮤지컬, 예술의전당, 부산)" autocomplete="off"><div id="sr" class="sr-list"></div></div>', ad(),
            '<p><a class="btn" href="/weekend/">이번 주말 %d건</a> <a class="btn" href="/free/">무료 %d건</a> <a class="btn" href="/ending/">곧 끝나는 %d건</a></p>' % (len(W), len(F), len(E)),
            '<h2 class="group-title">종류별</h2><div class="card-grid">%s</div>' % cards_realm(by_realm), '<h2 class="group-title">지역별</h2><div class="card-grid">%s</div>' % "".join('<a class="card" href="/region/%s/"><b>%s</b><span>%d건</span></a>' % (q(a), esc(a), len(L)) for a, L in sorted(by_area.items(), key=lambda t: -len(t[1]))),
            '<h2 class="group-title">최근 등록된 공연·전시</h2>', etable(new, 10), '<script src="/assets/js/search.js"></script>']
    faq = [("공연·전시 일정은 어디서 가져왔나요?", "한국문화정보원 문화포털이 공공데이터포털에 공개한 '한눈에보는문화정보' 데이터를 매일 받아 정리합니다. 문화포털에 등록된 일정만 포함되므로 모든 공연·전시를 담지는 않습니다."),
           ("예매는 어디서 하나요?", "각 공연·전시 상세 페이지의 예매·상세 정보 링크로 이동해 예매처에서 예매합니다. 이 사이트는 예매를 대행하지 않습니다."),
           ("무료 공연·전시도 있나요?", "있습니다. 요금이 무료로 안내된 행사를 따로 모았습니다. 사전 예약이 필요한 경우가 있으니 상세를 확인하세요.")]
    ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "우아전시공연", "url": BASE + "/", "potentialAction": {"@type": "SearchAction", "target": BASE + "/?q={q}", "query-input": "required name=q"}}]
    write("/", layout("/", "공연·전시 일정 찾기 - 지역별 무료·이번 주말 %s건 | 우아전시공연" % "{:,}".format(len(ev)), "문화포털에 등록된 공연·전시·행사 %s건을 지역·종류·무료 여부로 찾고 일정과 요금을 확인하세요." % "{:,}".format(len(ev)), "\n".join(body), faq, None, "website", ld, coupang=True), "1.0")
    idx = [[p["title"], ("/event/%s/" % p["seq"]) if p["d"] else ("/type/%s/" % REALM_SLUG[p["realm"]]), p["place"], rg(p), p["ed"][2:]] for p in sorted(ev, key=lambda p: -int(p["seq"]))]
    (OUT / "search_index.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pages_static(len(ev))
    finish()
    print("장소 허브", nv)


def cards_realm(by_realm):
    return "".join('<a class="card" href="/type/%s/"><b>%s</b><span>%d건</span></a>' % (q(REALM_SLUG[r]), esc(r), len(by_realm[r])) for r in REALMS if r in by_realm)


def pages_static(n):
    body = ['<div class="page-head"><h1>공연·전시 찾는 방법과 이용 안내</h1></div>', ad(),
            '<h2 class="group-title">1. 이 사이트에서 찾기</h2><ol class="lead"><li><a href="/weekend/">이번 주말</a>, <a href="/free/">무료</a>, <a href="/ending/">곧 끝나는</a> 목록에서 바로 고르거나</li><li><a href="/region/">지역별</a>·<a href="/type/">종류별</a>로 좁힙니다.</li><li>상세 페이지에서 기간·장소·요금을 보고 예매 링크로 이동합니다.</li></ol>',
            '<h2 class="group-title">2. 방문 전 확인할 점</h2><ul class="lead"><li><b>휴관일·회차</b>는 장소마다 달라 방문 전에 확인하세요.</li><li><b>무료 행사</b>도 사전 예약이 필요한 경우가 있습니다.</li><li><b>요금</b>은 좌석·회차에 따라 달라질 수 있습니다.</li></ul>',
            '<div class="note-box">이 사이트는 문화포털에 등록된 일정만 정리한 참고용이며 예매를 대행하지 않습니다.</div>']
    write("/guide/", layout("/guide/", "공연·전시 찾는 방법과 이용 안내", "공연·전시 일정을 지역·종류·무료 여부로 찾고 방문 전 확인할 점을 정리했습니다.", "\n".join(body), None, [("홈", "/"), ("이용 안내", "/guide/")]), "0.6")
    body = ['<div class="page-head"><h1>데이터 설명</h1></div>', '<p class="lead">우아전시공연은 한국문화정보원 <b>한눈에보는문화정보조회서비스</b>(공공데이터포털 15138937)를 매일 받아 정리합니다. 현재 %d건이 게시돼 있습니다. 상세(요금·예매 링크·문의)는 호출 한도 때문에 매일 일부씩 받아 쌓으므로 상세 페이지가 아직 없는 행사가 있을 수 있습니다. 종료된 행사는 목록에서 사라집니다.</p>' % n]
    write("/about/", layout("/about/", "데이터 설명", "우아전시공연이 사용하는 문화포털 공공데이터와 정리 방법을 설명합니다.", "\n".join(body), None, [("홈", "/"), ("데이터 설명", "/about/")]), "0.3")
    body = ['<div class="page-head"><h1>개인정보처리방침</h1></div>', '<p class="lead">우아전시공연은 회원가입·로그인 없이 이용하며 개인정보를 수집하지 않습니다. 사이트 개선을 위해 Google Analytics가 익명 방문 통계를 수집하고, Google AdSense와 쿠팡 파트너스가 광고를 표시하면서 쿠키를 사용할 수 있습니다. 게시된 일정 정보는 공공데이터포털에 공개된 자료입니다.</p>']
    write("/privacy/", layout("/privacy/", "개인정보처리방침", "우아전시공연 개인정보처리방침", "\n".join(body), None, [("홈", "/"), ("개인정보처리방침", "/privacy/")]), sitemap=False)


def finish():
    shutil.copytree(ROOT / "assets", OUT / "assets")
    for nf in ROOT.glob("naver*.html"):
        shutil.copy(nf, OUT / nf.name)
    today = TODAY.isoformat()
    urls = "".join("<url><loc>%s%s</loc><lastmod>%s</lastmod><priority>%s</priority></url>" % (BASE, q(p), today, pr) for p, pr in WRITTEN)
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>\n' % urls, encoding="utf-8")
    (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % BASE, encoding="utf-8")
    (OUT / "CNAME").write_text("wooashow.wooahouse.com\n", encoding="utf-8")
    nf = layout("/404.html", "페이지를 찾을 수 없습니다", "요청한 페이지를 찾을 수 없습니다. 종료된 행사 페이지는 삭제될 수 있습니다.", '<div class="page-head"><h1>페이지를 찾을 수 없습니다</h1><p>종료된 공연·전시 페이지는 삭제될 수 있습니다.</p></div><div class="chips"><a class="chip" href="/">홈</a><a class="chip" href="/weekend/">이번 주말</a><a class="chip" href="/free/">무료</a></div>', None, None, noindex=True)
    (OUT / "404.html").write_text(nf, encoding="utf-8")
    print("페이지", len(WRITTEN), "(sitemap)")


if __name__ == "__main__":
    build()
