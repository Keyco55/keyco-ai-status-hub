# Customizations

## 공개 가능한 사용자 기여

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

## 범위가 불확실한 부분

tmux status-right 설정은 현재 환경의 기존 설정과 backup이 동일해 이번 Work에서 새로 만든 변경인지 독립적으로 증명하지 못했습니다. 따라서 이 repo에서는 전체 tmux 설정을 복사하지 않고, 별도 예시 snippet으로만 제공합니다.

cmux.json과 Ghostty 설정에는 quota integration과 무관한 launcher·font 변경이 포함되어 있어 공개 범위에서 제외했습니다.

## 공개하지 않는 구현

- CodexBar의 provider 인증과 cookie 처리
- 실제 사용자 config
- account snapshot
- 실제 quota cache와 cost history
- compiled menu helper binary
- 개인 Mac의 LaunchAgent 실파일
- 전체 dev-cmux와 전체 terminal 설정

## 포트폴리오 표현 기준

권장 표현:

- CodexBar customization / integration
- AI usage monitoring
- macOS status-bar workflow
- privacy-preserving quota cache
- Multi-Agent model routing support

피해야 할 표현:

- CodexBar를 직접 개발했다
- CodexBar provider backend를 구현했다
- Multi-Agent orchestration 전체를 이 repo가 구현한다
