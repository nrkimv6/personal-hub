export function getErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    const msg = err.message;
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      return '서버에 연결할 수 없습니다';
    }
    if (/timeout|타임아웃/i.test(msg)) {
      return '요청 시간이 초과되었습니다';
    }
    return msg;
  }
  if (typeof err === 'string') return err;
  return String(err);
}
