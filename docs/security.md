# Security & Privacy

## Local-only network boundary

collector는 `127.0.0.1`에 바인딩된 CodexBar loopback endpoint에서 usage 정보를 읽습니다. 통신은 로컬 환경 안에서 이루어지며, Status Hub는 자체 public network service를 제공하지 않습니다.

## Data minimization

Status Hub는 화면 표시에 필요한 다음 정보만 status cache에 기록합니다.

- provider 상태
- remaining percentage
- reset 정보
- snapshot timestamp와 source label

credential, cookie, session token, account identity, raw provider response, billing 또는 cost history는 Status Hub가 별도로 저장하지 않습니다.

## Local cache protection

collector는 cache directory를 `0700`으로 만들고 status file을 `0600`으로 저장합니다. cache 갱신 시 temporary file에 먼저 기록하고 `fsync` 후 atomic replace를 수행합니다.

## Security boundary

Provider 인증과 session 관리는 upstream CodexBar 및 각 provider의 로컬 도구 안에 유지됩니다. Status Hub는 해당 로컬 usage 정보를 소비하는 integration layer이며 provider의 인증 또는 보안 기능을 대체하지 않습니다.
