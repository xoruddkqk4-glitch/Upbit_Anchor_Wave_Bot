# export_chat.py — 현재 Claude Code 세션 기록(JSONL)을 읽기 쉬운 대화 txt로 변환
#
# /export는 CLI 내장 명령이라 스킬 안에서 호출할 수 없으므로, Claude Code가 세션마다 남기는
#   ~/.claude/projects/<프로젝트키>/<세션ID>.jsonl
# 을 직접 읽어 같은 목적의 txt를 만든다. 세션 ID를 함께 출력해 `claude -r <세션ID>` 재개 명령을 안내할 수 있다.
#
# 사용:  python export_chat.py <출력파일.txt> [--session <세션ID>]
#   - 세션 미지정 시 프로젝트 폴더에서 가장 최근에 수정된 jsonl(=현재 세션)을 사용
#   - 종료 코드 0: 성공 / 2: 세션 기록을 찾지 못함 (호출부는 사용자에게 `/export <파일>`을 안내)
#
# 포함: 사용자·어시스턴트 텍스트 전체, 도구 호출 1줄 요약, 도구 결과 앞부분(200자)
# 제외: thinking 블록, 서브에이전트(isSidechain) 기록, 첨부/시스템 메타 레코드

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
TOOL_RESULT_PREVIEW = 200
TOOL_INPUT_PREVIEW = 160


def project_key(cwd: str) -> str:
  """Claude Code가 프로젝트 폴더명을 만드는 규칙: 영숫자 외 문자를 '-'로 치환"""
  return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd))


def find_session_file(session_id: str | None) -> Path:
  proj_dir = Path.home() / ".claude" / "projects" / project_key(os.getcwd())
  if not proj_dir.is_dir():
    raise FileNotFoundError(f"프로젝트 세션 폴더 없음: {proj_dir}")
  if session_id:
    p = proj_dir / f"{session_id}.jsonl"
    if not p.is_file():
      raise FileNotFoundError(f"세션 파일 없음: {p}")
    return p
  candidates = sorted(proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
  if not candidates:
    raise FileNotFoundError(f"세션 jsonl 없음: {proj_dir}")
  return candidates[0]


def to_kst(ts: str | None) -> datetime | None:
  if not ts:
    return None
  try:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST)
  except ValueError:
    return None


def one_line(s: str, limit: int) -> str:
  s = re.sub(r"\s+", " ", s).strip()
  return s if len(s) <= limit else s[: limit - 1] + "…"


def block_text(content) -> str:
  """tool_result 등의 content(str 또는 [{type:text}] 리스트)에서 텍스트만 추출"""
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
  return ""


def render_blocks(role: str, content) -> list[str]:
  out: list[str] = []
  if isinstance(content, str):
    if content.strip():
      out.append(content.rstrip())
    return out
  if not isinstance(content, list):
    return out
  for b in content:
    if not isinstance(b, dict):
      continue
    t = b.get("type")
    if t == "text":
      if b.get("text", "").strip():
        out.append(b["text"].rstrip())
    elif t == "tool_use":
      inp = b.get("input") or {}
      desc = inp.get("description") if isinstance(inp, dict) else None
      summary = desc or one_line(json.dumps(inp, ensure_ascii=False), TOOL_INPUT_PREVIEW)
      out.append(f"[도구 호출] {b.get('name')} — {summary}")
    elif t == "tool_result":
      txt = block_text(b.get("content"))
      if txt.strip():
        out.append(f"[도구 결과] {one_line(txt, TOOL_RESULT_PREVIEW)}")
    # thinking 블록은 기록하지 않음
  return out


def export(session_file: Path, out_path: Path) -> tuple[int, int]:
  user_n = assistant_n = 0
  lines: list[str] = []
  last_day = None
  with session_file.open(encoding="utf-8") as f:
    for raw in f:
      try:
        r = json.loads(raw)
      except json.JSONDecodeError:
        continue
      if r.get("type") not in ("user", "assistant") or r.get("isSidechain"):
        continue
      msg = r.get("message") or {}
      role = "사용자" if r["type"] == "user" else "Claude"
      rendered = render_blocks(role, msg.get("content"))
      if not rendered:
        continue
      ts = to_kst(r.get("timestamp"))
      if ts and ts.date() != last_day:
        last_day = ts.date()
        lines.append(f"\n===== {last_day.isoformat()} (KST) =====")
      stamp = ts.strftime("%H:%M") if ts else "--:--"
      # 도구 결과만 있는 user 레코드는 '사용자' 발화가 아니므로 역할 표기를 바꾼다
      if role == "사용자" and all(x.startswith("[도구 결과]") for x in rendered):
        role = "도구"
      elif role == "사용자":
        user_n += 1
      else:
        assistant_n += 1
      lines.append(f"\n[{stamp}] {role}:")
      lines.extend(rendered)

  now = datetime.now(KST)
  header = [
      "Claude Code 대화 기록 (save-djt 스킬로 생성)",
      f"내보낸 시각 : {now.strftime('%Y-%m-%d %H:%M')} KST",
      f"세션 ID     : {session_file.stem}",
      f"재개 명령   : claude -r {session_file.stem}",
      f"프로젝트    : {os.getcwd()}",
      f"원본 기록   : {session_file}",
      "=" * 72,
  ]
  out_path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
  return user_n, assistant_n


def main() -> int:
  args = sys.argv[1:]
  if not args:
    print("사용법: python export_chat.py <출력파일.txt> [--session <세션ID>]")
    return 1
  out_path = Path(args[0])
  session_id = None
  if "--session" in args:
    i = args.index("--session")
    session_id = args[i + 1] if i + 1 < len(args) else None
  try:
    session_file = find_session_file(session_id)
  except FileNotFoundError as e:
    print(f"[실패] {e}")
    return 2
  user_n, assistant_n = export(session_file, out_path)
  print(f"[완료] {out_path} (사용자 {user_n}건 / Claude {assistant_n}건)")
  print(f"SESSION_ID={session_file.stem}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
