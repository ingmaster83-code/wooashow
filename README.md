# 우아전시공연 (wooashow)

한국문화정보원 한눈에보는문화정보조회서비스(공공데이터포털 15138937, `apis.data.go.kr/B553457/cultureinfo`)로 만든 공연·전시·행사 일정 사이트(Python 정적 생성기). https://wooashow.wooahouse.com

- `scripts/fetch_data.py` — `period2`(오늘~+400일, serviceTp A 공연/전시·B 행사/축제·C 교육/체험)로 목록(약 1,000건), 처음 보는 seq만 `detail2`로 상세(가격·예매 URL·문의·주소)를 받아 `data/details/{seq//2000}.json.gz`에 누적. 목록에서 사라지면 제거. 하루 예산 800호출. 응답이 이중 이스케이프(`&amp;lt;`)라 빌드에서 unescape 2회.
- 이 데이터는 문화포털 등록분만이라 규모가 작다(진행·예정 약 1,000건). 더 큰 공연 데이터(KOPIS)는 별도 키 발급이 필요.
- `scripts/build_site.py` — 행사 상세(상세 보유분), 종류·지역·장소·무료·이번 주말·곧 끝나는·월별 허브, 검색 인덱스. 이미지(thumbnail)는 저작권·혼합콘텐츠 때문에 쓰지 않는다.
- 날짜 기준 페이지(이번 주말·곧 끝나는·월별)는 빌드 날짜(KST)로 계산되므로 매일 빌드가 필요.
- Actions: 매일 KST 06:00 fetch → 데이터 커밋 → 빌드 → 배포. 레포 시크릿 `API_KEY` 필요.
