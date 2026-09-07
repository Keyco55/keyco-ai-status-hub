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
