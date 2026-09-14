# keyco AI Status Hub

여러 AI 코딩 서비스를 동시에 사용하면서 각 서비스의 사용량과 초기화 시간을 매번 따로 확인해야 하는 불편을 줄이기 위해 만든 macOS 개발환경 도구입니다.

이 프로젝트는 CodexBar를 새로 만든 프로젝트가 아닙니다. CodexBar를 기반 데이터 공급원으로 활용하고, 그 로컬 usage 데이터를 개인정보가 남지 않는 status cache로 변환해 macOS 메뉴바·tmux·cmux와 Multi-Agent model routing 판단에 연결합니다.

## 프로젝트 소개

현재 개발환경에서는 Codex, Antigravity, Alibaba Token Plan을 함께 사용합니다. 각 provider의 quota와 reset 시간을 한 곳에서 확인할 수 있으면, 작업을 시작할 때 어떤 모델과 provider를 선택할지 더 빠르게 판단할 수 있습니다.

이 저장소에는 그 목적을 위해 직접 작성하거나 수정한 integration layer만 담습니다.

## 왜 만들었나

사용량 확인을 위해 여러 provider 화면을 번갈아 열면 작업 흐름이 끊깁니다. 그래서 CodexBar의 로컬 loopback usage API를 주기적으로 읽고, 화면 표시에 필요한 최소한의 값만 별도 cache에 저장하도록 구성했습니다.

이 도구의 핵심은 메뉴바를 꾸미는 것이 아니라 다음 판단을 돕는 것입니다.

AI Provider Usage

→ Quota / Reset 확인

→ Dynamic Model Routing 판단

→ 병렬 Worktree에 Worker 배치

→ Independent Senior Review

→ Human QA

## 주요 기능

- Codex, Antigravity, Alibaba Token Plan usage 조회
- quota 값 정규화
- reset 시간 파싱과 countdown 표시
- 조회 실패 시 unavailable 표시
- 이전 값과 현재 상태를 구분하는 stale cache
- identity, credential, raw response를 저장하지 않는 status cache
- atomic cache write
- cache directory 0700, file 0600 권한 적용
- AppKit 기반 AG / CC / C / ALI 메뉴바 표시
- tmux·cmux에서 읽을 수 있는 간단한 상태 출력

## 현재 사용 환경

- macOS 메뉴바
- CodexBar local server
- Python standard library 기반 collector
- Swift AppKit 기반 menu helper
- tmux와 cmux workflow

CodexBar는 Peter Steinberger의 별도 오픈소스 프로젝트입니다. 이 저장소는 CodexBar 자체의 source나 binary를 포함하지 않습니다.

## 동작 구조

자세한 흐름은 docs/architecture.md에 정리했습니다.

1. CodexBar가 provider usage를 조회합니다.
2. Python collector가 loopback endpoint를 읽습니다.
3. collector가 표시 가능한 quota·reset·source만 추출합니다.
   Antigravity가 offline이면 AGY 공식 status line payload의 최신 quota cache를 fallback으로 사용합니다.
4. 별도 status cache에 atomic write합니다.
5. 메뉴바·terminal·cmux가 cache를 읽습니다.
6. 사람은 quota와 reset 상태를 보고 model routing을 결정합니다.

## 제가 직접 구현한 부분

- CodexBar loopback usage API 연동
- provider response에서 quota window를 정규화하는 로직
- reset timestamp와 설명값 처리
- stale cache와 unavailable 상태 처리
- 민감한 원본 response를 저장하지 않는 cache schema
- atomic write와 restrictive permission 처리
- AppKit status item과 threshold 표시
- cmux·terminal에서 상태를 확인하는 integration snippet

CodexBar provider 조회 방식, 인증, cookie 처리 자체는 이 프로젝트의 구현 범위가 아닙니다.

## 기술 구성

- Python 3
- Swift / AppKit
- macOS LaunchAgent template
- CodexBar local HTTP API
- POSIX file permission과 atomic replace

별도 Python package, Swift package, JavaScript dependency는 사용하지 않습니다.

## Multi-Agent 개발환경과의 연결

이 repo가 Multi-Agent orchestration 전체를 구현하는 것은 아닙니다. 이 도구는 Multi-Agent 개발환경에서 모델 선택과 resource routing 판단을 지원하는 status/monitoring layer입니다.

예를 들어 quota가 낮거나 reset이 가까운 provider를 확인하면, 작업의 성격과 남은 resource를 함께 고려해 Worker와 Senior Review에 사용할 model을 선택할 수 있습니다.

## 설치 및 사용 방법

1. upstream CodexBar를 먼저 설치합니다.
2. CodexBar에서 사용할 provider와 인증을 설정합니다. 인증 정보는 CodexBar의 로컬 설정에서 관리됩니다.
3. src/ai-resource-hud를 로컬 실행 경로에 배치합니다.
4. src/ai-resource-hud-menu.swift를 AppKit helper로 빌드합니다.
5. launchd/*.example.plist의 placeholder를 현재 환경에 맞게 치환합니다.
6. LaunchAgent를 등록한 뒤 collector와 menu helper의 동작을 확인합니다.

Swift helper 예시:

~~~sh
swiftc -O -o "$HOME/.local/bin/ai-resource-hud-menu" \
  "$HOME/.local/bin/ai-resource-hud-menu.swift" \
  -framework AppKit
~~~

CodexBar local server 예시:

~~~sh
codexbar serve --host 127.0.0.1 --port 8097 \
  --refresh-interval 120 --request-timeout 30
~~~

실제 provider 인증값과 개인별 설정은 CodexBar의 로컬 설정에서 관리해야 합니다.

Antigravity fallback 설정 예시:

~~~json
{
  "statusLine": {
    "type": "command",
    "command": "~/.local/bin/ai-resource-hud --agy-statusline",
    "stack_with_default": true
  }
}
~~~

AGY가 보내는 전체 payload는 저장하지 않으며, quota의 remaining/reset 값만 별도 cache에 보관합니다.

## Antigravity Fallback 동작 방식

CodexBar의 Antigravity provider는 CodexBar/AGY CLI 버전 조합에 따라 독립적으로 offline일 수 있습니다(`source=offline`, 빈 응답, invalid JSON, transport 실패). Status Hub는 이 경우에도 동작을 유지합니다. CodexBar 자체를 수정하지 않습니다.

실제 runtime 데이터 흐름은 다음과 같습니다.

1. AGY 공식 statusLine이 매 tick마다 JSON payload을 `ai-resource-hud --agy-statusline`으로 전달합니다.
2. collector는 payload에서 quota의 remaining/reset 값만 추출해 `~/.cache/ai-resource-hud/antigravity-statusline.json`(`0600`)에 보관합니다. email, conversation/session ID, workspace path, transcript path, prompt, model 대화 내용은 저장하지 않습니다.
3. collector 수집 시 CodexBar의 Antigravity 상태가 ready가 아니면(offline 포함) fresh한 statusLine cache를 fallback으로 사용합니다. fresh한 fallback은 CodexBar 실패로 지워지지 않습니다.
4. 수집 결과는 status snapshot(`status.json`)에 기록되고, Swift menu helper와 terminal/cmux integration이 snapshot을 읽어 표시합니다.

5H quota가 있으면 5H를, 5H가 없고 Weekly만 있으면 Weekly를 표시합니다. 없는 값을 0으로 만들지 않습니다.

## Health와 설치 Provenance

- collector는 매 수집마다 sanitized health record(`~/.cache/ai-resource-hud/health.json`, `0600`)를 갱신합니다. 프로세스 종료 코드 0과 upstream 상태는 구분됩니다. 기록되는 것은 `last_collector_run`, `last_success`(직전 성공 시점 유지), `antigravity_source`, `antigravity_status`, `statusline_cache_state`, `codexbar_state`, `last_error_class`(허용된 error class만), `runtime_version`뿐이며 raw body, identity, token, path를 포함하지 않습니다.
- CodexBar 요청은 최대 2회 시도 안에서 monotonic 총 15초 budget으로 동작합니다. 각 시도의 timeout은 남은 budget으로 제한되고, budget이 소진되면 재시도하지 않습니다.
- `scripts/deploy-status-hub.sh`는 collector와 Swift helper를 같은 source tree에서 한 번에 설치합니다(Swift 빌드, ad-hoc 서명, 설치 후 hash 검증 포함). 설치는 transactional합니다. 첫 live 변경 이후의 모든 실패(명시적 오류뿐 아니라 `date`/hash/rename 같은 예기치 않은 실패 포함)는 rollback 경로로 복원되며, 복원 결과는 검증되고 검증된 경우에만 recovery backup을 정리합니다. 복원 자체가 실패하면 명시적 오류와 함께 backup을 보존합니다. manifest는 검증된 live artifact의 hash로 마지막에 기록됩니다. 목적지와 부모 디렉터리의 symlink, regular file이 아닌 목적지(FIFO/디렉터리 등)는 거부하고 따라가지 않으며 기록하지 않습니다.
- `--verify-only`는 hash뿐 아니라 provenance까지 검증합니다. 같은 clean-source 정책을 요구하고, manifest의 key 집합이 정확히 일치하는지, `source_commit`이 source HEAD와 같은지, hash가 설치된 artifact와 같은지 확인합니다.
- 실제 배포는 clean committed source에서만 허용됩니다. tracked/staged/untracked(무시되지 않은) 변경이 있으면 배포를 거부합니다.
- 설치 provenance는 `~/.cache/ai-resource-hud/install.json`(`0600`)에 기록되며 `schema_version`, `source_commit`, `collector_sha256`, `menu_sha256`, `installed_at`, `runtime_version`만 포함합니다. 실제 배포가 아니라면 `--home`에 임시 root를 지정해 검증만 수행하고, LaunchAgent 재시작이나 AGY 설정 변경은 하지 않습니다.

## Status Cache 구조

examples/status.example.json은 실제 사용값이 아닌 예시 데이터입니다. 실제 cache에는 다음 범주의 값만 남기는 것을 목표로 합니다.

- provider status
- source label
- remaining percentage
- reset timestamp
- collector runtime version
- snapshot timestamp

account email, account ID, cookie, token, raw provider response, 비용 history는 저장하지 않습니다.

## 개인정보 보호 설계

- collector는 proxy를 사용하지 않고 loopback endpoint만 요청합니다.
- raw provider response는 status cache에 저장하지 않습니다.
- cache에는 표시에 필요한 상태와 quota/reset 정보만 기록합니다.
- credential, cookie, account identity를 Status Hub가 별도로 저장하지 않습니다.
- cache directory에는 `0700`, cache file에는 `0600` 권한을 적용합니다.
- 임시 파일을 만든 뒤 atomic replace로 cache를 갱신합니다.

## CodexBar와의 관계

CodexBar는 이 프로젝트의 데이터 공급원입니다. CodexBar 자체를 제작했다거나 upstream source를 수정했다고 주장하지 않습니다.

upstream CodexBar는 MIT License 프로젝트이며, 자세한 출처와 attribution은 ATTRIBUTION.md에 기록했습니다.

## 라이선스 및 출처

이 저장소의 직접 작성 code는 LICENSE의 조건으로 배포합니다. CodexBar는 별도 프로젝트이며 upstream MIT License와 저작권 고지를 존중합니다.
