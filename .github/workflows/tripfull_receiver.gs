/**
 * 트립풀 브리핑 폴백 수신기 (Apps Script 웹앱, doPost)
 * ------------------------------------------------------------------
 * generate_tripfull.py 가 POST 하는 마크다운 텍스트를 받아
 * 드라이브 '트립풀 브리핑' 폴더에 Google Docs 로 저장한다.
 *
 * ★ 선택 발송의 핵심(skip 로직):
 *   같은 이름( "트립풀 브리핑 YYYY-MM-DD" )의 파일이 폴더에 이미 있으면
 *   (= Cowork/Claude 가 먼저 만든 리치판) 저장하지 않고 skipped:true 를 반환한다.
 *   → 발송기(v18)는 폴더에 남은 '한 개' 문서를 09:00 에 파싱·발송한다.
 *
 * 배포:
 *   1) script.google.com 새 프로젝트 → 이 코드 붙여넣기
 *   2) 프로젝트 설정 → 스크립트 속성에 TRIPFULL_TOKEN 추가(임의 비밀문자열,
 *      GitHub Secret APPS_SCRIPT_TOKEN 과 동일 값)
 *   3) 배포 → 새 배포 → 유형: 웹 앱
 *      - 실행 계정: 나
 *      - 액세스 권한: 모든 사용자(익명) 또는 링크 소유자
 *   4) 배포 URL 을 GitHub Secret TRIPFULL_APPS_SCRIPT_URL 에 등록
 *
 * 응답(JSON):
 *   { ok:true, skipped:true,  id, name }        // 오늘자 문서 이미 존재
 *   { ok:true, skipped:false, id, name, url }   // 폴백 새로 저장
 *   { ok:false, error }                          // 토큰 불일치·예외
 */

// 저장 폴더(트립풀 브리핑). POST parentId 가 오면 그 값을 우선 사용.
var DEFAULT_FOLDER_ID = '11l9noIRPwfgGrP0_STRa7C8cGuloEgKG';

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return _json({ ok: false, error: 'no post body' });
    }
    var body = JSON.parse(e.postData.contents);

    // 1) 토큰 검증
    var expected = PropertiesService.getScriptProperties().getProperty('TRIPFULL_TOKEN');
    if (!expected || body.token !== expected) {
      return _json({ ok: false, error: 'invalid token' });
    }

    var title = (body.title || '').trim();
    var text = body.text || '';
    var parentId = (body.parentId || DEFAULT_FOLDER_ID).trim();
    if (!title || !text) {
      return _json({ ok: false, error: 'title/text required' });
    }

    var folder = DriveApp.getFolderById(parentId);

    // 2) skip 로직 — 오늘자 문서가 이미 있으면 Cowork 우선, 저장하지 않음
    var existing = folder.getFilesByName(title);
    if (existing.hasNext()) {
      var f = existing.next();
      return _json({ ok: true, skipped: true, id: f.getId(), name: title });
    }

    // 3) 마크다운 텍스트 → Google Docs 생성(발송기 v18 이 본문 텍스트를 파싱)
    var doc = DocumentApp.create(title);
    doc.getBody().setText(text);
    doc.saveAndClose();

    // 4) 루트에서 목표 폴더로 이동
    var file = DriveApp.getFileById(doc.getId());
    folder.addFile(file);
    try { DriveApp.getRootFolder().removeFile(file); } catch (ignore) {}

    return _json({
      ok: true,
      skipped: false,
      id: file.getId(),
      name: title,
      url: 'https://drive.google.com/open?id=' + file.getId()
    });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// 상태 점검용(브라우저로 URL 열면 200)
function doGet() {
  return _json({ ok: true, service: 'tripfull-receiver', ts: new Date().toISOString() });
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
