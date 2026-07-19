#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${GAME_ROOM_HOST:-127.0.0.1}"
PORT="${GAME_ROOM_PORT:-8777}"
PID_FILE="$APP_DIR/.gameroom.pid"
LOG_FILE="$APP_DIR/.gameroom.log"

usage() {
  cat <<USAGE
Usage: $0 {start|stop|restart|status|url}

Environment:
  GAME_ROOM_HOST   default: 127.0.0.1
  GAME_ROOM_PORT   default: 8777
USAGE
}

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

start() {
  if is_running; then
    echo "The Game Room is already open at http://$HOST:$PORT/ (pid $(cat "$PID_FILE"))"
    return 0
  fi

  cd "$APP_DIR"
  nohup env GAME_ROOM_HOST="$HOST" GAME_ROOM_PORT="$PORT" python3 "$APP_DIR/server.py" >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 0.4

  if is_running; then
    echo "The Game Room is open at http://$HOST:$PORT/ (pid $(cat "$PID_FILE"))"
  else
    echo "The Game Room failed to open. Log: $LOG_FILE" >&2
    rm -f "$PID_FILE"
    return 1
  fi
}

stop() {
  if ! is_running; then
    echo "The Game Room is not running."
    rm -f "$PID_FILE"
    return 0
  fi

  kill "$(cat "$PID_FILE")"
  rm -f "$PID_FILE"
  echo "The Game Room is closed."
}

status() {
  if is_running; then
    echo "The Game Room is open at http://$HOST:$PORT/ (pid $(cat "$PID_FILE"))"
  else
    echo "The Game Room is not running."
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  url) echo "http://$HOST:$PORT/" ;;
  *) usage; exit 2 ;;
esac
