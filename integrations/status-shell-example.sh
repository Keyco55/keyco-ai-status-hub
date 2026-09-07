#!/usr/bin/env sh

# 실제 cache의 내용을 출력하지 않고, collector가 제공하는 요약 상태만 표시합니다.
exec "$HOME/.local/bin/ai-resource-hud" --status
