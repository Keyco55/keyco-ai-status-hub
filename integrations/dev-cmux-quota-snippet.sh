#!/usr/bin/env zsh

# dev-cmux에 병합할 수 있는 최소 quota 표시 예시입니다.
# 전체 dev-cmux와 프로젝트별 launcher 설정은 복사하지 않습니다.

quota_status() {
  local hud="$HOME/.local/bin/ai-resource-hud"

  if [[ ! -x "$hud" ]]; then
    print -r -- "AG -- · CC -- · C -- · ALI -- · UNAVAILABLE"
    return 0
  fi

  "$hud" --cmux 2>/dev/null \
    || print -r -- "AG -- · CC -- · C -- · ALI -- · UNAVAILABLE"
}

# 예시:
# print -- "QUOTA   : $(quota_status)"
