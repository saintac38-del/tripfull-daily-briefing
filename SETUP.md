# 트립풀 폴백 — GitHub 셋업 체크리스트

인스타 루틴과 동일 패턴의 **트립풀 데일리 브리핑 폴백**입니다.
Cowork(Claude)가 실패하면 GitHub Actions가 Gemini로 브리핑을 만들어 같은 폴더에 저장하고,
발송기(Apps Script v18)가 09:00에 그 문서를 메일로 보냅니다.

## 파일 구성 (레포에 이 트리 그대로 추가)

```
generate_tripfull.py                 # 폴백 생성기(마크다운 출력)
requirements.txt                     # 표준 lib만 — 그대로
.github/workflows/daily-tripfull.yml # cron 08:40 KST + 수동 실행
tripfull_receiver.gs                 # Apps Script 수신기(skip 로직) — 레포엔 참고용, 실제는 script.google.com에 배포
```

인스타 파일들과 이름이 겹치지 않으므로 **같은 레포에 그대로 추가**하면 됩니다.

## 1단계 — Apps Script 수신기 배포

1. script.google.com → 새 프로젝트 → `tripfull_receiver.gs` 내용 붙여넣기
2. 프로젝트 설정 → 스크립트 속성 → `TRIPFULL_TOKEN` = (임의 비밀문자열)
3. 배포 → 새 배포 → 웹 앱 / 실행: 나 / 액세스: 모든 사용자
4. 최초 실행 시 드라이브 권한 승인
5. 배포 URL 복사 → 아래 Secret 에 사용

> ⚠️ 권한 승인은 본인이 브라우저에서 직접 해야 합니다(자동화 불가).

## 2단계 — GitHub Secrets 등록

레포 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 | 인스타와 공용? |
|---|---|---|
| `TAVILY_API_KEY` | Tavily 키 | ✅ 공용 가능 |
| `GEMINI_API_KEY` | Gemini 키 | ✅ 공용 가능 |
| `GEMINI_MODEL` | (선택) `gemini-2.5-flash` | ✅ |
| `APPS_SCRIPT_TOKEN` | 1단계 `TRIPFULL_TOKEN`과 동일 값 | ⚠️ 값이 같아야 함 |
| `TRIPFULL_APPS_SCRIPT_URL` | 1단계 배포 URL | ❌ 트립풀 전용 |
| `TRIPFULL_DRIVE_PARENT_ID` | (선택) `11l9noIRPwfgGrP0_STRa7C8cGuloEgKG` | ❌ 미설정 시 코드 기본값 사용 |

## 3단계 — 발송기(v18)와의 관계

- 트립풀 발송기 Apps Script(v18)는 **변경 불필요.** 폴백판도 v18 파서가 읽는
  동일 섹션 구조(트립풀 픽·핫이슈·트렌드·오늘의 역사·콘텐츠 아이디어)로 나옵니다.
- 이중 발송 걱정 없음: 폴더엔 skip 로직으로 **오늘자 문서가 항상 1개**만 남습니다.

## 4단계 — 최초 테스트 (수동)

1. 레포 → Actions → **Daily Tripfull Briefing (fallback)** → **Run workflow**
2. 로그 확인:
   - `Gemini 폴백 파일을 새로 생성함` → 저장 성공(오늘 Cowork 파일 없었음)
   - `오늘 Cowork 파일이 이미 있어 건너뜀` → skip 정상(리치판 우선)
3. 드라이브 `트립풀 브리핑` 폴더에서 `트립풀 브리핑 YYYY-MM-DD` 문서 확인

## 동작 타임라인 (매일)

| 시각(KST) | 주체 | 동작 |
|---|---|---|
| ~08:0x | Cowork(Claude) | 리치 브리핑 생성 → 폴더 저장 |
| 08:40 | GitHub Actions | 폴백 생성 → 수신기 저장 시도(오늘자 있으면 skip) |
| 09:00 | Apps Script v18 | 폴더의 오늘자 문서 1개 파싱 → 메일 발송 |
| 12:00 | Apps Script v18 | (재시도) 미발송 시 재발송 |

## 조정 포인트

- Cowork 완료가 08:40보다 늦으면 cron을 `50 23 * * *`(08:50) 등으로 늦추세요.
  단 발송(09:00) 전 여유는 남겨야 합니다.
- 폴백을 더 정교하게/간결하게 원하면 `generate_tripfull.py`의 `build_prompt()`
  섹션 지시를 조정하면 됩니다(섹션 '제목'은 파서 호환 위해 유지).
