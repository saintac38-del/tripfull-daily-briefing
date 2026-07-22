#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tripfull Daily — 트립풀 데일리 콘텐츠 브리핑 '폴백' 자동 생성 (서버측, 무료 조합)

흐름: Tavily 검색 → Gemini 작성(마크다운 섹션) → 트립풀 수신기(Apps Script doPost)로
      드라이브 '트립풀 브리핑' 폴더에 저장. 오늘자 문서가 이미 있으면(=Cowork/Claude가
      먼저 만듦) 수신기가 skip → Cowork 리치판을 그대로 둔다. 없으면 이 폴백판을 저장한다.
      그 뒤 별도 발송기(Apps Script v18)가 폴더의 오늘자 문서 1개를 파싱해 메일로 보낸다.

★ 인스타 루틴과의 결정적 차이:
  인스타 폴백은 '완성 HTML'을 만들지만, 트립풀은 발송기(v18)가 섹션을 파싱해 HTML을
  '직접 조립'한다. 따라서 이 폴백은 HTML이 아니라 v18 파서가 읽는 '마크다운 섹션 문서'를
  출력한다. → 이메일 디자인이 Cowork판·폴백판 동일하게 유지된다. harden_html() 불필요.

필요 환경변수(GitHub Secrets):
  TAVILY_API_KEY            Tavily 검색 API 키 (무료 1,000/월) — 인스타와 공용 가능
  GEMINI_API_KEY           Google Gemini API 키 (무료 ~1,500/일) — 인스타와 공용 가능
  GEMINI_MODEL             (선택) 기본 'gemini-2.5-flash'
  TRIPFULL_APPS_SCRIPT_URL 트립풀 수신기 웹앱 배포 URL (doPost) — tripfull_receiver.gs
  APPS_SCRIPT_TOKEN        수신기 공유 비밀 토큰 (임의 문자열) — 인스타와 공용 가능
  TRIPFULL_DRIVE_PARENT_ID (선택) 저장 폴더 ID. 기본값=트립풀 브리핑 폴더.
"""
import os
import re
import sys
import json
import time
import datetime
import zoneinfo
import urllib.request
import urllib.error

# ---- 설정 -------------------------------------------------------------
# 트립풀 브리핑 폴더(운영). 인스타와 달리 '이 폴더에 경쟁 저장'하는 것이 정상 동작이므로
# 기본값을 둔다. 필요 시 환경변수로 덮어쓸 수 있다(테스트 폴더 등).
DEFAULT_TRIPFULL_FOLDER = "11l9noIRPwfgGrP0_STRa7C8cGuloEgKG"
# 'or' 사용: 시크릿 미설정 시 GitHub이 빈 문자열("")을 넘겨도 기본값으로 떨어지게 한다.
DRIVE_PARENT_ID = os.environ.get("TRIPFULL_DRIVE_PARENT_ID") or DEFAULT_TRIPFULL_FOLDER

# 'gemini-flash-latest' 별칭은 무료 티어에서 503(과부하)이 잦았음 → 정식 모델명 기본.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"

KST = zoneinfo.ZoneInfo("Asia/Seoul")

# 트립풀 나침반: 이동 · 교류 · 경계 · 문명
# 요일별 심층 우산 테마(SKILL.md v5.5 §4 회전표)
WEEKDAY_THEME = {
    0: "서아시아·이슬람 세계(페르시아·오스만·아랍·중앙아시아 / 제국·교역·신앙·번역운동·유목-정주)",
    1: "동아시아 해양 세계(중국·일본·류큐·동남아 / 항구도시·조공무역·이주·표류·해적·도자기 교역)",
    2: "유럽의 전환기(르네상스·대항해·과학혁명·계몽 / 식민과 탈식민 재해석·인쇄혁명·도시사)",
    3: "한국사 다시 읽기(고대~근현대 / 발굴·사료·인물·변방과 경계·교류사)",
    4: "아메리카·아프리카 문명(잉카·마야·아즈텍·안데스 / 사하라이남 왕국·누비아 고고학)",
    5: "유물과 박물관(세계 특별전·발굴 속보 / 유물 과학·약탈문화재 반환·큐레이션 이면)",
    6: "먹고 마시는 세계사(음식·향신료·기호품 / 교역로가 바꾼 식탁·조리기술·기근과 식량)",
}
# 요일별 경제/크리에이터 주제
WEEKDAY_BIZ = {
    0: "미국·유럽 독립출판 트렌드·성공사례",
    1: "크라우드펀딩 성공사례(텀블벅·Kickstarter)",
    2: "작가 브랜딩·1인 미디어 수익화·뉴스레터",
    3: "전자책·오디오북 한국 시장 성장·독자 변화",
    4: "유튜브·릴스 인문·역사 채널 알고리즘",
    5: "북페어·도서전·서울 국제 출판 행사",
    6: "독서 인구 통계·서점 트렌드·한국 독자",
}


# ---- 유틸 -------------------------------------------------------------
def http_post_json(url, payload, headers=None, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tavily_search(query, api_key, max_results=4):
    """Tavily 검색. 정제된 본문 스니펫과 URL을 반환."""
    try:
        out = http_post_json(
            "https://api.tavily.com/search",
            {
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",      # 1 크레딧
                "max_results": max_results,
                "include_answer": False,
                "topic": "news",
                "days": 3,                     # 최근 3일 우선(핫이슈 신선도)
            },
        )
        items = []
        for r in out.get("results", []):
            items.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("content", "") or "")[:600],
            })
        return items
    except Exception as e:
        print(f"[warn] Tavily 검색 실패 ({query}): {e}", file=sys.stderr)
        return []


def build_queries(now):
    """오늘 날짜·요일에 맞춰 검색 쿼리를 동적으로 만든다(연도 고정 금지, 당일 명시)."""
    mm = now.month
    dd = now.day
    yyyy = now.year
    en_month = now.strftime("%B")
    theme = WEEKDAY_THEME[now.weekday()]
    biz = WEEKDAY_BIZ[now.weekday()]
    return [
        f"{mm}월 {dd}일 역사적 사건 인물 탄생 사망",       # 오늘의 역사(국내/세계)
        f"{en_month} {dd} in history events",              # 오늘의 역사(영문 보조)
        f"world news today {en_month} {dd} {yyyy}",        # 세계 핫이슈(당일)
        f"{yyyy}년 {mm}월 {dd}일 주요 뉴스",                # 국내 핫이슈(당일)
        f"{yyyy}년 {mm}월 문화 역사 발굴 유산 전시",         # 국내 문화·역사
        f"{en_month} {yyyy} history culture travel discovery",  # 국제 문화·여행
        f"{theme} 역사 문명 교류",                          # 요일 심층테마
        f"{yyyy}년 {mm}월 {biz}",                           # 경제/크리에이터
    ]


def collect_research(now):
    api_key = os.environ["TAVILY_API_KEY"]
    blocks = []
    for q in build_queries(now):
        results = tavily_search(q, api_key)
        block = f"### 검색: {q}\n"
        for r in results:
            block += f"- [{r['title']}]({r['url']}) — {r['content']}\n"
        blocks.append(block)
    return "\n".join(blocks)


# ---- Gemini 프롬프트 (마크다운 섹션 — v18 파서용) ---------------------
def build_prompt(date_str, date_kr, weekday_kr, now, research):
    theme = WEEKDAY_THEME[now.weekday()]
    biz = WEEKDAY_BIZ[now.weekday()]
    return f"""너는 트립풀(Tripfull Publishing, 인문·문화사 1인 독립출판사)의
콘텐츠 검증 컨설턴트이자 편집자다. 운영자는 루시안(1978, 경기 화성).
"트립풀 데일리 콘텐츠 브리핑"을 한국어로, 충실하게 작성한다.
이 결과물은 이메일 발송기가 '섹션 제목'을 그대로 파싱하므로, 아래 지정한
섹션 제목·형식을 글자 그대로 지켜라(제목의 이모지·문구를 바꾸지 말 것).

[트립풀 나침반] 모든 픽·딥다이브는 이동·교류·경계·문명 중 하나 이상에 닿는다.
[오늘 날짜] {date_kr} ({weekday_kr})
[오늘의 요일 심층테마] {theme}
[오늘의 경제/크리에이터 주제] {biz}

[사실 검증 규칙 — 매우 중요]
· 모든 사실 주장(뉴스·수치·사건)에는 반드시 [매체명](전체 https URL) 형식 링크를 붙인다.
  URL 없는 출처 표기 금지. 아래 검색 자료에 근거하고, 자료에 없으면 지어내지 말 것.
· 검증 표기는 ✓ Verified 또는 [확인 필요] 두 가지만 사용. '신뢰도 %' 절대 금지.
· 모호 표현 금지: "대부분", "~라고 알려져 있다", "많은 사람들이", "급증", "화제",
  "충격적", "역대급" 등. 구체적 수치·날짜·기관명·인물명으로 대체.
· 오늘의 역사는 반드시 오늘 날짜({date_kr})와 일치하는 사건만. 위키/나무위키 단독 인용 지양.
· 감정·해석 표현은 자유. 사실 문장만 위 규칙을 따른다.

[검색 자료 — 핫이슈·트렌드·오늘의 역사 근거용]
{research}

[출력 문서 구조 — 아래 순서·제목을 그대로. 빈 섹션 금지]
첫 줄은 정확히: `# 🗓 트립풀 데일리 콘텐츠 브리핑 — {date_kr}`
그 다음 한 줄: `> 요일 심층테마: {theme} · 경제/크리에이터: {biz}`
그리고 `> ⚠️ 이 문서는 GitHub 폴백 자동 생성본(Gemini)입니다. Cowork 리치판 부재 시 발송됩니다.`

## ⭐ 오늘의 트립풀 픽
- 소제목(굵게) 1개. 이동·교류·경계·문명에 닿는 오늘의 역사/이슈 기반.
- 제목 2종: (롱폼) 분석적 / (인스타 훅) 짧은 질문·반전형.
- 선정 근거 2~3문장(구체 수치·연도·인물 포함, 출처 링크).
📱 인스타 완성본
- 캡션 5~7줄. 첫 줄=훅(통념 깨기), 끝 줄=질문/CTA. 본문에 구체 수치·고유명사 1개 이상.
- 해시태그 정확히 10개, #트립풀 필수.
- 추천 이미지 1~2줄(저작권 안전: 직접촬영/CC0/퍼블릭도메인/박물관 OA 우선).
🎬 유튜브/릴스 훅 3개
- 각 한 문장, 호기심·반전형, 서로 다른 진입각.

## 🔥 오늘의 핫이슈 — 세계 & 국내
### [국내]
- 3~4건. 각: **제목** → 1~2문장(날짜·수치·기관·인물) → [매체명](URL) + 필요시 [확인 필요].
### [세계]
- 3~4건. 같은 형식. 당일 발행 기사 우선.

## 📊 분야별 트렌드
- 4건. 각: **분야** + 한 줄 핵심(수치 포함) + [매체명](URL).

## 🏛 오늘의 역사
- 3~4건, 세계사 1~2 + 한국사 1~2 균형. 오늘 날짜와 일치.
- 각: **[연도] 사건/인물(정식명칭+생몰)** → 1~2문장 → ▶ 트립풀 앵글 1줄(이동·교류·경계·문명) → [매체명](URL).

## 📝 오늘의 콘텐츠 아이디어
- 6건. 각 `[라벨] 앵글+채널+확장 한 문장` + 끝에 실행성 태그 〔1차자료: 유/무 · 난이도: 하/중/상 · 시리즈: ○○버킷〕.

[출력 규칙]
완성된 마크다운 전체만 출력. 코드펜스(```), 머리말, 설명 일절 금지.
첫 글자는 반드시 '#'. 위 6개 `##` 섹션 제목을 하나도 빠뜨리지 말 것."""


# 일시적 오류(과부하·혼잡)로 간주해 재시도할 HTTP 상태코드
TRANSIENT_CODES = {429, 500, 502, 503, 504}


def gemini_generate(prompt, max_retries=5):
    api_key = os.environ["GEMINI_API_KEY"]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 16384,
            # Gemini 2.5 Flash의 'thinking' 토큰이 출력 예산을 잡아먹어 본문이 잘리는 것을 방지.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    out = None
    for attempt in range(1, max_retries + 1):
        try:
            out = http_post_json(url, payload, timeout=180)
            break
        except urllib.error.HTTPError as e:
            if e.code in TRANSIENT_CODES and attempt < max_retries:
                wait = min(2 ** attempt, 30)
                print(f"[warn] Gemini {e.code} 일시 오류, {wait}s 후 재시도 "
                      f"({attempt}/{max_retries})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    if out is None:
        raise RuntimeError("Gemini 응답 없음")
    text = out["candidates"][0]["content"]["parts"][0]["text"].strip()
    # 혹시 코드펜스가 붙으면 제거
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def save_to_drive(title, text):
    """트립풀 수신기(doPost)로 마크다운 텍스트를 전송. 오늘자 문서 존재 시 수신기가 skip."""
    out = http_post_json(
        os.environ["TRIPFULL_APPS_SCRIPT_URL"],
        {
            "token": os.environ["APPS_SCRIPT_TOKEN"],
            "title": title,
            "text": text,          # ← 인스타는 html, 트립풀은 마크다운 text
            "parentId": DRIVE_PARENT_ID,
        },
        timeout=120,
    )
    return out


# ---- 완결성 검사 ------------------------------------------------------
REQUIRED_SECTIONS = ("트립풀 픽", "오늘의 핫이슈", "분야별 트렌드",
                     "오늘의 역사", "콘텐츠 아이디어")


def validate_markdown(md):
    """v18 파서가 읽을 최소 조건: '#'로 시작 + 필수 섹션 존재 + 충분한 길이."""
    if not md.lstrip().startswith("#"):
        return "첫 글자가 '#'가 아님(마크다운 형식 오류)"
    missing = [s for s in REQUIRED_SECTIONS if s not in md]
    if missing:
        return f"필수 섹션 누락: {', '.join(missing)}"
    if len(md) < 1500:
        return f"본문이 너무 짧음(잘림 의심). 길이={len(md)}자"
    return None


# ---- 메인 -------------------------------------------------------------
def main():
    now = datetime.datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")                       # 2026-07-22
    date_kr = now.strftime("%Y년 %m월 %d일")                  # 2026년 07월 22일
    weekday_kr = "월화수목금토일"[now.weekday()] + "요일"
    # ★ 제목은 Cowork(Claude)가 만드는 것과 '동일'해야 skip이 작동한다.
    title = f"트립풀 브리핑 {date_str}"
    print(f"[info] {title} 폴백 생성 시작 ({weekday_kr})")

    research = collect_research(now)
    if not research.strip():
        print("[error] 검색 자료가 비었습니다. 중단.", file=sys.stderr)
        sys.exit(1)

    prompt = build_prompt(date_str, date_kr, weekday_kr, now, research)
    md = gemini_generate(prompt)

    err = validate_markdown(md)
    if err:
        print(f"[error] 출력 검증 실패: {err}. 저장하지 않고 중단.", file=sys.stderr)
        print(md[:500], file=sys.stderr)
        sys.exit(1)

    # 저장. 오늘 파일이 이미 있으면(=Cowork가 먼저 만든 경우) 수신기가 skipped 응답.
    result = save_to_drive(title, md)
    print("[done] 저장 결과:", json.dumps(result, ensure_ascii=False))
    if not result.get("ok"):
        print(f"[error] 저장 실패: {result.get('error')}", file=sys.stderr)
        sys.exit(1)  # GitHub에 빨간 실패로 표시
    if result.get("skipped"):
        print("[info] 오늘 Cowork 파일이 이미 있어 건너뜀 — Claude 리치판 우선. 정상.")
    else:
        print("[info] Gemini 폴백 파일을 새로 생성함 (오늘 Cowork 파일 없었음).")


if __name__ == "__main__":
    main()
