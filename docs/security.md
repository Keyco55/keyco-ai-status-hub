# Security & Privacy

## Local-only network boundary

collector는 `127.0.0.1`에 바인딩된 CodexBar loopback endpoint에서 usage 정보를 읽습니다. 통신은 로컬 환경 안에서 이루어지며, Status Hub는 자체 public network service를 제공하지 않습니다.

Antigravity fallback은 공식 status line stdin payload를 처리하지만 원본 payload는 저장하지 않습니다. `email`, `conversation_id`, workspace path 등은 폐기하고 quota의 remaining/reset 값만 `0600` cache에 기록합니다.

## Data minimization

Status Hub는 화면 표시에 필요한 다음 정보만 status cache에 기록합니다.

- provider 상태
- remaining percentage
- reset 정보
- snapshot timestamp와 source label

credential, cookie, session token, account identity, raw provider response, billing 또는 cost history는 Status Hub가 별도로 저장하지 않습니다.

## Local cache protection

collector는 cache directory를 `0700`으로 만들고 status file을 `0600`으로 저장합니다. cache 갱신 시 temporary file에 먼저 기록하고 `fsync` 후 atomic replace를 수행합니다. statusLine fallback cache(`antigravity-statusline.json`), health record(`health.json`), install manifest(`install.json`)에도 동일한 atomic write와 `0600` 규칙을 적용합니다.

## StatusLine fallback privacy

공식 AGY statusLine payload에는 email, conversation/session ID, workspace path, transcript path 등이 포함될 수 있습니다. collector는 이 중 quota bucket의 `remaining_fraction`, `reset_time`(`resetAt`으로 정규화), `source`/`status`/`lastSuccessAt` timestamp metadata만 보관하고, 그 외의 모든 identity/context 필드와 raw payload 전체를 폐기합니다. response body는 어떤 경우에도 로그에 남기지 않으며, CodexBar 수집 실패는 `transport_error` / `invalid_json` / `provider_offline` 같은 error class로만 기록됩니다.

방어 차원에서 loader는 cache 파일을 그대로 반환하지 않고 whitelist(`status`, `source`, `lastSuccessAt`, 허용된 quota metric의 `remainingPercent`/`resetAt`)로 record를 재구성합니다. 직접 수정되거나 구버전인 cache에 identity 필드가 들어 있어도 status snapshot으로 전파되지 않습니다. `source == "offline"`인 CodexBar record는 metric이 남아 있어도 절대 현재 READY quota로 취급하지 않습니다.

## Health and provenance minimization

health record는 허용된 operational field(`schema_version`, `last_collector_run`, `last_success`, `antigravity_source`, `antigravity_status`, `statusline_cache_state`, `codexbar_state`, `last_error_class`, `runtime_version`)만 포함하고, 허용되지 않은 error class 값은 기록되지 않습니다. install manifest는 `schema_version`, `source_commit`, `collector_sha256`, `menu_sha256`, `installed_at`, `runtime_version`만 포함하며, 절대 worktree 경로, account, token, conversation/session ID, workspace path를 저장하지 않습니다.

## Security boundary

Provider 인증과 session 관리는 upstream CodexBar 및 각 provider의 로컬 도구 안에 유지됩니다. Status Hub는 해당 로컬 usage 정보를 소비하는 integration layer이며 provider의 인증 또는 보안 기능을 대체하지 않습니다.
