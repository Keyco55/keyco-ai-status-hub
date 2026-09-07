# Portfolio Summary — keyco AI Status Hub

## Intro

`keyco AI Status Hub`는 여러 AI 코딩 서비스를 함께 사용하는 개발환경에서 quota와 reset 상태를 한곳에 모아 보여주는 macOS status/monitoring integration layer입니다.

이 프로젝트의 목적은 새로운 AI provider나 모델 실행기를 만드는 것이 아닙니다. 사람이 여러 작업과 모델을 운영할 때 resource 상태를 빠르게 확인하고, 다음 모델과 작업 흐름을 판단할 수 있도록 기존 local usage 정보를 작은 표시용 상태 레이어로 정리하는 것입니다.

## Problem

Codex, Antigravity, Alibaba Token Plan처럼 여러 provider를 동시에 사용하면 각 서비스의 사용량과 reset 시점을 따로 확인해야 합니다. 이 과정은 작업 흐름을 끊고, 어떤 provider를 Worker나 Senior Review에 사용할지 판단하는 시간을 늘립니다.

특히 quota가 낮거나 reset이 가까운 provider를 늦게 발견하면, 작업을 중단하거나 다른 model로 전환하는 판단도 늦어집니다.

## Solution

CodexBar가 제공하는 loopback local usage API에서 필요한 값만 읽어 Python collector가 공통 metric으로 정규화합니다. collector는 raw response 대신 표시 가능한 quota·reset·상태만 sanitized JSON cache에 기록합니다. Swift/AppKit 메뉴바 helper와 terminal/cmux integration은 같은 cache를 읽습니다.

```text
CodexBar Local Usage API
        ↓
Python Collector
        ↓
Sanitized Status Cache
        ↓
macOS Menu Bar · Terminal · cmux
        ↓
Human Model Routing Decision
```

이 흐름에서 최종 model 선택, Worker/Senior 배치, worktree 운영은 사람이 판단합니다. Status Hub가 model을 자동 선택하거나 Multi-Agent orchestration 전체를 실행하지는 않습니다.

## Direct contribution

직접 구현한 범위는 다음과 같습니다.

- loopback `/usage` endpoint 소비
- Codex, Antigravity, Alibaba Token Plan response의 quota window 정규화
- remaining percentage와 reset 값 파싱
- reset countdown을 위한 표시용 시간 계산
- `ready`, `stale`, `unavailable` 상태 분리
- raw provider response에서 display-safe 값만 추출하는 cache schema
- 임시 파일과 atomic replace를 이용한 cache 갱신
- cache directory `0700`, status file `0600` 권한 처리
- Swift/AppKit 기반 `AG`, `CG`, `C`, `ALI` status item 표시
- quota threshold에 따른 ready, stop, warning, countdown 표시
- terminal, tmux/cmux에서 읽는 상태 출력과 integration snippet

구현 근거는 [`src/ai-resource-hud`](../src/ai-resource-hud), [`src/ai-resource-hud-menu.swift`](../src/ai-resource-hud-menu.swift), [`integrations/`](../integrations/), [`docs/architecture.md`](architecture.md)에 남겼습니다.

## Tech

- Python 3 standard library
- Swift / AppKit
- local HTTP loopback API
- JSON status cache
- macOS LaunchAgent example templates
- shell-based terminal/cmux integration
- POSIX file permission과 atomic file replacement

CodexBar의 provider 인증, cookie 처리, provider backend 자체는 이 프로젝트의 직접 구현 범위가 아닙니다.

## Privacy

Status Hub는 account identity, credential, cookie, token, raw provider response, cost history를 status cache에 저장하지 않습니다. Demo asset은 합성 데이터를 사용합니다.

Provider 인증은 별도 설치된 CodexBar와 로컬 환경에서 관리되며, Status Hub는 표시 가능한 usage 상태만 소비합니다.

## Multi-Agent connection

Status Hub는 사용자가 여러 AI model과 agent를 병렬로 운영하는 개발환경에서 resource 상태를 확인하고 routing 판단을 내리도록 돕습니다.

정확한 포지셔닝은 다음과 같습니다.

> 사용자가 직접 여러 AI 모델을 운영하는 개발환경에서 quota/reset 정보를 빠르게 확인하고 다음 모델 선택을 판단할 수 있도록 만든 macOS status/monitoring integration layer.

이 저장소는 Multi-Agent orchestration 전체, 자동 model routing, tmux 전체 설정을 구현한다고 주장하지 않습니다.

## Current status

- Portfolio state: `Public / Portfolio Ready`
- Repository: https://github.com/Keyco55/keyco-ai-status-hub
- Default remote branch: `main`
- LICENSE holder: `Copyright (c) 2026 keyco`
