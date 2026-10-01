#!/bin/bash
# Full-page redraw time per screen (ms, 3 runs each): ./bench.sh [host]
H=http://${1:-192.168.1.159}; TOK=$(cat /tmp/sd_token)
curl -s -X POST "$H/api/swipe?dir=right" >/dev/null; for i in 1 2 3 4 5; do curl -s -X POST "$H/api/swipe?dir=right" >/dev/null; done; sleep 2
for i in 0 1 2 3 4 5; do
  curl -s -m 20 -X POST -H "X-OTA-Token: $TOK" "$H/api/bench/render"; echo
  curl -s -X POST "$H/api/swipe?dir=left" >/dev/null; sleep 2.5
done
curl -s -X POST "$H/api/swipe?dir=none" >/dev/null
