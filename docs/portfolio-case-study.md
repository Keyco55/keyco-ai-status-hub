# Case Study — keyco AI Status Hub

## Problem

여러 AI 코딩 서비스를 병렬로 사용하는 개발환경에서는 provider마다 quota와 reset 정보를 확인하는 위치가 다릅니다. 사용량을 확인하려고 여러 화면을 오가면 작업 흐름이 끊기고, resource가 부족한 provider를 늦게 발견할 수 있습니다.

필요했던 것은 또 하나의 provider client가 아니라, 이미 로컬에서 확인 가능한 usage 정보를 사람이 빠르게 읽을 수 있는 공통 status layer였습니다.

## Solution

CodexBar의 loopback local usage API를 데이터 공급원으로 사용하고, Python collector가 provider별 응답에서 quota window와 reset 정보를 정규화합니다. 표시용 값만 sanitized status cache에 기록한 뒤 Swift/AppKit menu bar, terminal, cmux가 같은 cache를 읽도록 연결했습니다.

결과적으로 사용자는 한 화면에서 provider 상태를 비교하고, 작업 성격·남은 resource·reset 시점을 함께 고려해 다음 model과 review 흐름을 선택할 수 있습니다.

## My Contribution

현재 소스에서 확인된 사용자 측 구현·튜닝·integration 범위는 다음과 같습니다.

1. **Local usage integration** — loopback `/usage` endpoint에서 provider usage snapshot을 읽는 collector 연결
2. **Metric normalization** — Codex 5-hour/weekly, Antigravity Gemini·Claude/GPT window, Alibaba Token Plan 7-day window를 공통 `remainingPercent`와 reset field로 정리
3. **Reset parsing** — ISO timestamp, epoch-like numeric value, 제한된 설명 문자열을 표시 가능한 reset 정보로 변환
4. **State handling** — provider 응답이 없거나 metric이 불완전할 때 `unavailable`, 이전 유효 metric을 유지할 때 `stale`로 구분
5. **Sanitized cache** — account identity, credential, raw response를 저장하지 않고 status·source·metric·runtime snapshot만 기록
6. **Safe cache update** — temporary file, `fsync`, atomic replace, directory `0700`, file `0600` 처리
7. **Menu bar display** — Swift/AppKit status item에서 `AG`, `CG`, `C`, `ALI`를 표시하고 threshold에 따라 ready, stop, warning, countdown을 구분
8. **Terminal/cmux integration** — 같은 cache에서 `--status`, `--tmux`, `--cmux` 출력을 만들고 shell snippet으로 개발환경에 연결

직접 확인 가능한 근거는 [`src/ai-resource-hud`](../src/ai-resource-hud), [`src/ai-resource-hud-menu.swift`](../src/ai-resource-hud-menu.swift), [`integrations/status-shell-example.sh`](../integrations/status-shell-example.sh), [`integrations/dev-cmux-quota-snippet.sh`](../integrations/dev-cmux-quota-snippet.sh)입니다.

## Architecture

```text
CodexBar Local API
        ↓
Python Collector
        ↓
Sanitized Status Cache
   ↙       ↓        ↘
Menu Bar  Terminal   cmux
        \   |       /
     Human Model Routing Decision
```

Mermaid 원본은 [`portfolio-architecture.mmd`](portfolio-architecture.mmd)에, 기존 architecture 설명은 [`architecture.md`](architecture.md)에 보존했습니다.

합성 데이터를 사용한 화면 예시는 [`status-hub-demo.svg`](screenshots/status-hub-demo.svg)에서 확인할 수 있습니다.

경계는 명확합니다.

- CodexBar: provider usage 조회와 local API 제공
- Python collector: 응답 필터링, metric 정규화, 상태 cache 작성
- Swift/AppKit: cache를 읽는 macOS status item과 menu 표시
- Terminal/cmux: 사람이 읽는 요약 상태 출력
- Human: model 선택, agent 역할 배치, worktree와 QA 순서 결정

## Privacy / Security

Status Hub의 data boundary는 다음과 같습니다.

- CodexBar의 credential, cookie, token, session을 별도로 저장하지 않음
- account email, account ID, cost history를 status cache에 저장하지 않음
- raw provider response 대신 표시 가능한 metric만 기록
- demo 화면은 합성 sample data를 사용
- cache 작성 시 restrictive permission과 atomic replacement를 사용
- collector는 loopback 주소의 local endpoint만 요청하고 proxy를 사용하지 않음

이 설계는 수집·보관되는 데이터 범위를 줄이는 integration 경계입니다. Provider 인증 자체나 외부 서비스의 보안 기능을 대신하지 않습니다.

## Multi-Agent Development

여러 AI model을 Worker, Senior Review, QA 등 서로 다른 역할에 사용할 때 현재 quota와 reset 상태를 빠르게 확인하고, 사람이 routing 결정을 내릴 수 있도록 지원합니다.

## CodexBar Relationship

이 repository는 [CodexBar](https://github.com/steipete/CodexBar)의 fork가 아니며, CodexBar 자체를 개발했다고 주장하지 않습니다.

CodexBar는 Peter Steinberger의 별도 MIT License 프로젝트이고, 이 프로젝트는 CodexBar가 제공하는 local usage API의 consumer/integration layer입니다. provider 인증, cookie 처리, provider backend source와 binary는 이 repository의 배포 대상이 아닙니다.

upstream 고지와 MIT License 전문은 [`ATTRIBUTION.md`](../ATTRIBUTION.md)와 [`third_party/CodexBar-LICENSE.txt`](../third_party/CodexBar-LICENSE.txt)에 기록했습니다.

## Current Status

`Public / Portfolio Ready`

GitHub repository는 https://github.com/Keyco55/keyco-ai-status-hub 에 PUBLIC으로 제공되며 default branch는 `main`입니다. LICENSE holder는 `Copyright (c) 2026 keyco`입니다.

## Project Positioning

Status Hub는 CodexBar를 upstream data source로 사용하는 local usage/status integration layer입니다. Quota와 reset 정보를 macOS status 및 terminal 환경에 제공하며, model routing은 사용자가 결정합니다. Status Hub 자체는 automatic orchestration platform이 아닙니다.
