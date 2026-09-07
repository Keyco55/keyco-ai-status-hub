# 설정 예시

이 파일은 실제 CodexBar config를 복사한 것이 아닙니다. credential 없이 필요한 실행 흐름만 설명합니다.

## 권장 provider

현재 integration layer에서 확인한 provider ID는 다음과 같습니다.

- antigravity
- codex
- alibabatokenplan

provider 인증은 CodexBar의 Settings 또는 공식 CLI 흐름에서 직접 설정합니다. cookie header, API key, token은 이 저장소의 sample이나 README에 기록하지 않습니다.

## Local server

~~~sh
codexbar serve --host 127.0.0.1 --port 8097 \
  --refresh-interval 120 --request-timeout 30
~~~

collector는 다음 loopback endpoint만 요청합니다.

~~~text
http://127.0.0.1:8097/usage?provider=all
~~~

외부 주소에 server를 열거나 실제 인증값을 command history에 남기는 구성은 이 sample의 목적이 아닙니다.
