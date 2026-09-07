# Security

## 공개 저장소에 넣지 않는 것

- API key, access token, refresh token
- cookie header와 session
- account email과 account ID
- reset credit ID
- raw provider response
- 실제 quota cache와 usage history
- cost database
- 개인 Mac의 LaunchAgent와 absolute path
- compiled binary와 backup

## Cache 보호

collector는 cache directory를 0700으로 만들고 status file을 0600으로 저장합니다. 임시 파일에 먼저 기록한 뒤 atomic replace를 사용합니다.

cache에는 provider status, source label, remaining percentage, reset timestamp, snapshot timestamp 정도만 보관합니다.

## 네트워크 경계

collector는 CodexBar가 제공하는 loopback endpoint만 요청합니다. server는 127.0.0.1에 바인딩하는 구성을 전제로 합니다. 외부 interface에 공개하거나 reverse proxy 뒤에 노출하는 구성은 이 repo의 범위가 아닙니다.

## 공개 전 점검

~~~sh
git status --short
git ls-files
# Run the local secret scanner against credential-like values.
# Search the tree for personal email patterns and machine-specific paths.
find . -type f \( -name '*.sqlite' -o -name '*.bak' -o -name '*.pyc' -o -name '*.app' \)
~~~

검색 결과가 source 설명의 일반적인 단어가 아니라 실제 credential이나 개인정보를 가리키면 공개를 중단하고 파일을 제거하거나 sample로 교체해야 합니다.

## Credential rotation

기존 CodexBar config 또는 backup에 manual cookie가 있었다면 공개 repo와 별개로 해당 session을 폐기하고 provider에서 수동 재로그인하는 것을 검토해야 합니다. 이 repo는 기존 credential 파일을 삭제하거나 logout하지 않습니다.
