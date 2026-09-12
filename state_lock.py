# state_lock.py
# ==============================================================================
# bot_state.json 동시 쓰기 방지용 파일 락 (외부 의존성 없음)
#
# Upbit_Anchor_Wave_Bot.py(5분 주기)와 scan_ref_candles.py(09:07)가 같은 상태 파일을
# load -> 수정 -> save 하므로, 두 실행이 겹치면 나중에 저장한 쪽이 상대의 변경을 지운다.
# (예: 봇이 기록한 체결(entry_bought)이 스캐너의 오래된 사본으로 덮여 유령 포지션 발생)
# 실행 전체를 이 락으로 감싸 직렬화한다. 느린 봇 실행이 다음 크론 틱과 겹치는 경우도 막아준다.
#
# os.O_EXCL 원자적 파일 생성에 의존하므로 같은 머신의 프로세스 간에만 유효하다.
# ==============================================================================

import os
import time


class StateFileLock:
  """`<state_file>.lock` 파일을 원자적으로 생성해 소유권을 표현하는 단순 락

  - acquire(): timeout_sec 동안 poll_sec 간격으로 재시도. 실패 시 False (호출부가 실행을 건너뜀)
  - 락 파일이 stale_sec보다 오래됐으면 이전 프로세스가 비정상 종료한 것으로 보고 회수한다.
    (정상 실행은 수 분을 넘지 않으므로 기본 15분은 충분히 보수적)
  """

  def __init__(self, state_file, timeout_sec=120, stale_sec=900, poll_sec=1.0):
    self.lock_path = f"{state_file}.lock"
    self.timeout_sec = timeout_sec
    self.stale_sec = stale_sec
    self.poll_sec = poll_sec
    self._owned = False

  def acquire(self):
    deadline = time.monotonic() + self.timeout_sec
    while True:
      try:
        fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
          os.write(fd, f"pid={os.getpid()} at={time.time():.0f}\n".encode("utf-8"))
        finally:
          os.close(fd)
        self._owned = True
        return True
      except FileExistsError:
        if self._is_stale():
          # 두 대기자가 동시에 stale 판정 후 서로의 새 락을 지우는 경쟁은 이론상 가능하나,
          # "죽은 프로세스의 락 + 같은 초에 두 대기자"가 겹쳐야 하므로 2프로세스 크론 환경에서는 무시한다.
          self._remove_quietly()
          continue
        if time.monotonic() >= deadline:
          return False
        time.sleep(self.poll_sec)

  def release(self):
    if self._owned:
      self._remove_quietly()
      self._owned = False

  def _is_stale(self):
    try:
      return (time.time() - os.path.getmtime(self.lock_path)) > self.stale_sec
    except OSError:
      # 판정 사이에 소유자가 해제한 경우 -> 다음 루프에서 정상 획득 시도
      return False

  def _remove_quietly(self):
    try:
      os.remove(self.lock_path)
    except OSError:
      pass

  def __enter__(self):
    return self.acquire()

  def __exit__(self, exc_type, exc, tb):
    self.release()
    return False
