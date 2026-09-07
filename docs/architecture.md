# Architecture

이 프로젝트의 역할은 provider 인증이나 AI model 실행이 아니라, 로컬 usage 정보를 사람이 routing 판단에 사용할 수 있는 작은 상태 레이어로 바꾸는 것입니다.

~~~mermaid
flowchart TD
    A[CodexBar Local API] --> B[Python Collector]
    B --> C[Sanitized Status Cache]
    C --> D[macOS Menu Bar]
    C --> E[Terminal / tmux]
    C --> F[cmux HUD]
    D --> G[Human Routing Decision]
    E --> G
    F --> G
    G --> H[Worker / Senior / QA Workflow]
~~~

## 경계

### CodexBar

provider별 usage를 조회하고 local server에서 JSON을 제공합니다. 인증과 cookie는 CodexBar의 설치·설정 경계에 남습니다.

### Python Collector

loopback endpoint를 읽고 provider별 metric을 공통 schema로 정규화합니다. 사용 가능한 값은 remaining percentage와 reset 정보이며, raw response는 저장하지 않습니다.

### Status Cache

메뉴바와 terminal이 읽는 작은 JSON 파일입니다. 예시 구조는 examples/status.example.json에서 확인할 수 있습니다.

### 표시 계층

Swift AppKit helper는 cache를 읽어 AG, CC, C, ALI status item을 표시합니다. cmux와 terminal integration은 같은 cache를 사람이 읽을 수 있는 문자열로 보여줍니다.

## Routing 연결

Status Hub는 model을 자동으로 선택하거나 agent를 실행하지 않습니다. quota와 reset 상태를 보여주고, 최종 model 선택과 worktree 배치는 사람이 판단합니다.
