# Integration Scope

## Status Hub integration

이 저장소는 CodexBar 앱 자체의 수정본이 아니라, CodexBar local usage API를 사용하는 별도 integration layer입니다.

확인된 기여 범위는 다음과 같습니다.

- Codex, Antigravity, Alibaba Token Plan provider 선택
- provider response에서 quota window를 공통 metric으로 정규화
- reset timestamp와 reset 설명값 파싱
- unavailable와 stale 상태 분리
- raw response에서 display-safe 값만 골라 cache에 저장
- atomic replace 방식의 cache 갱신
- cache directory 0700 및 status file 0600 처리
- AppKit status item 네 개의 표시 규칙
- quota threshold에 따른 ready, stop, warning, countdown 표시
- cmux와 terminal에서 status cache를 읽는 연결부

## Configuration scope

tmux와 cmux 연결은 기존 설정 전체를 대체하지 않고, status cache를 읽는 작은 예시 snippet으로 제공됩니다.

Launcher, font, terminal profile 같은 사용자별 설정은 Status Hub의 동작 범위에 포함되지 않습니다.

## Upstream and local boundaries

- CodexBar의 provider 인증과 cookie 처리
- 사용자별 CodexBar config
- account identity와 billing history
- 사용자별 LaunchAgent와 terminal 설정

## Project positioning

Status Hub는 CodexBar를 기반 데이터 공급원으로 사용하는 별도 integration layer입니다. AI usage monitoring, macOS status-bar workflow, 최소화된 quota cache, Multi-Agent model routing 판단 지원을 제공하며 CodexBar provider backend나 전체 Multi-Agent orchestration을 구현하지 않습니다.
