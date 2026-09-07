# Attribution

## CodexBar

이 프로젝트는 provider usage 데이터를 얻기 위해 Peter Steinberger의 CodexBar를 별도 설치본으로 사용합니다.

- Repository: https://github.com/steipete/CodexBar
- License: MIT
- Upstream author: Peter Steinberger
- 관계: 이 저장소는 CodexBar fork가 아니며 CodexBar source나 binary를 재배포하지 않습니다.

이 저장소의 collector는 CodexBar의 local usage endpoint가 제공하는 JSON 구조를 소비하는 integration code입니다. CodexBar의 내부 provider 구현이나 인증 코드는 이 저장소에 포함하지 않습니다.

upstream MIT License 전문은 third_party/CodexBar-LICENSE.txt에 보존했습니다.

## 직접 작성한 부분

Python collector, Swift AppKit menu helper, status cache schema, launchd template, terminal/cmux integration 예시는 이 프로젝트의 직접 작성 또는 사용자 환경에서 추출한 공개용 integration layer입니다.
