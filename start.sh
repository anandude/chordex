#!/usr/bin/env bash
# ChordLens one-command local runner.
#
# Usage:
#   ./start.sh              # Redis (Docker) + API + worker + frontend
#   ./start.sh --setup      # Install deps first, then start
#   ./start.sh --docker     # Full stack in Docker (no local frontend HMR)
#   ./start.sh --stop       # Stop everything started by this script / compose
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PID_DIR="${ROOT}/.run"
LOG_DIR="${ROOT}/.run/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${CYAN}→${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
die()   { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

SETUP=0
DOCKER=0
STOP=0
for arg in "$@"; do
  case "$arg" in
    --setup|-s) SETUP=1 ;;
    --docker|-d) DOCKER=1 ;;
    --stop) STOP=1 ;;
    --help|-h)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) die "Unknown option: $arg (try --help)" ;;
  esac
done

# ── stop ──────────────────────────────────────────────────────────────────────
stop_all() {
  info "Stopping ChordLens…"

  if [[ -f "$PID_DIR/api.pid" ]]; then
    kill "$(cat "$PID_DIR/api.pid")" 2>/dev/null || true
    rm -f "$PID_DIR/api.pid"
  fi
  if [[ -f "$PID_DIR/worker.pid" ]]; then
    kill "$(cat "$PID_DIR/worker.pid")" 2>/dev/null || true
    rm -f "$PID_DIR/worker.pid"
  fi
  if [[ -f "$PID_DIR/frontend.pid" ]]; then
    # kill process group if possible
    kill "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null || true
    # next can leave children
    pkill -f "next dev" 2>/dev/null || true
    rm -f "$PID_DIR/frontend.pid"
  fi

  # Only stop redis container we started
  if [[ -f "$PID_DIR/redis.container" ]]; then
    docker stop chordex-redis >/dev/null 2>&1 || true
    docker rm chordex-redis >/dev/null 2>&1 || true
    rm -f "$PID_DIR/redis.container"
  fi

  # Full compose stack
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$ROOT/docker-compose.yml" down >/dev/null 2>&1 || true
  fi

  ok "Stopped."
}

if [[ "$STOP" -eq 1 ]]; then
  stop_all
  exit 0
fi

# ── docker full stack ─────────────────────────────────────────────────────────
if [[ "$DOCKER" -eq 1 ]]; then
  command -v docker >/dev/null || die "Docker is required for --docker mode"
  info "Starting full stack with Docker Compose…"
  docker compose up --build -d
  ok "API:      http://localhost:8000"
  ok "Health:   http://localhost:8000/health"
  warn "Frontend is not in compose — run: cd frontend && npm run dev"
  warn "Or use:  ./start.sh   (hybrid mode with frontend)"
  echo
  echo "Logs: docker compose logs -f"
  echo "Stop: ./start.sh --stop"
  exit 0
fi

# ── prerequisites ─────────────────────────────────────────────────────────────
command -v docker >/dev/null || die "Docker is required (used for Redis). Install Docker, then retry."
command -v node >/dev/null || die "Node.js is required. Install Node 18+."
command -v python3 >/dev/null || die "Python 3 is required."

# ── setup (optional / first run) ──────────────────────────────────────────────
ensure_backend() {
  if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
    info "Creating Python venv…"
    python3 -m venv "$ROOT/backend/.venv"
  fi
  # shellcheck disable=SC1091
  source "$ROOT/backend/.venv/bin/activate"

  if ! python -c "import fastapi, librosa, redis, rq" 2>/dev/null; then
    info "Installing backend dependencies (first time can take a few minutes)…"
    bash "$ROOT/backend/install_deps.sh"
  fi

  if [[ ! -f "$ROOT/backend/.env" ]]; then
    cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
    ok "Created backend/.env from example"
  fi
}

ensure_frontend() {
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    info "Installing frontend dependencies…"
    (cd "$ROOT/frontend" && npm install)
  fi
  if [[ ! -f "$ROOT/frontend/.env.local" ]]; then
    cp "$ROOT/frontend/.env.example" "$ROOT/frontend/.env.local"
    ok "Created frontend/.env.local from example"
  fi
}

if [[ "$SETUP" -eq 1 ]] || [[ ! -x "$ROOT/backend/.venv/bin/python" ]] || [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  info "Running setup…"
  ensure_backend
  ensure_frontend
  # fixtures (optional, non-fatal)
  if [[ ! -f "$ROOT/test-assets/c_f_g_c.wav" ]]; then
    info "Generating test audio fixtures…"
    "$ROOT/backend/.venv/bin/python" "$ROOT/test-assets/generate_fixtures.py" || true
  fi
else
  # light ensure
  # shellcheck disable=SC1091
  source "$ROOT/backend/.venv/bin/activate"
  ensure_frontend
fi

# ── Redis ─────────────────────────────────────────────────────────────────────
ensure_redis() {
  if redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
    ok "Redis already running on :6379"
    return
  fi
  info "Starting Redis in Docker (chordex-redis)…"
  docker rm -f chordex-redis >/dev/null 2>&1 || true
  docker run -d --name chordex-redis -p 6379:6379 redis:7-alpine >/dev/null
  echo "chordex-redis" > "$PID_DIR/redis.container"
  # wait for ready
  for i in $(seq 1 30); do
    if redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
      ok "Redis ready"
      return
    fi
    sleep 0.3
  done
  die "Redis failed to start. Check: docker logs chordex-redis"
}

ensure_redis

# ── export env for local processes ────────────────────────────────────────────
export REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
export UPLOAD_DIR="${UPLOAD_DIR:-/tmp/chordex_uploads}"
export CHORD_ENGINE="${CHORD_ENGINE:-auto}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:3000}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
mkdir -p "$UPLOAD_DIR"

# ── cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
  echo
  info "Shutting down (Ctrl+C)…"
  stop_all
}
trap cleanup INT TERM

# Kill any stale local processes from a previous run
if [[ -f "$PID_DIR/api.pid" ]] || [[ -f "$PID_DIR/worker.pid" ]] || [[ -f "$PID_DIR/frontend.pid" ]]; then
  warn "Cleaning up previous run…"
  stop_all
  # restart redis if we just killed our container
  ensure_redis
fi

# ── start services ────────────────────────────────────────────────────────────
info "Starting API (port 8000)…"
(
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
) >"$LOG_DIR/api.log" 2>&1 &
echo $! > "$PID_DIR/api.pid"

info "Starting worker…"
(
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  exec python worker.py
) >"$LOG_DIR/worker.log" 2>&1 &
echo $! > "$PID_DIR/worker.pid"

info "Starting frontend (port 3000)…"
(
  cd "$ROOT/frontend"
  exec npm run dev -- --port 3000
) >"$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$PID_DIR/frontend.pid"

# wait for API health
info "Waiting for API…"
API_OK=0
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    API_OK=1
    break
  fi
  sleep 0.5
done
if [[ "$API_OK" -ne 1 ]]; then
  warn "API not healthy yet — see $LOG_DIR/api.log"
  tail -20 "$LOG_DIR/api.log" || true
else
  ok "API healthy"
fi

# wait for frontend
info "Waiting for frontend…"
FE_OK=0
for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:3000 >/dev/null 2>&1; then
    FE_OK=1
    break
  fi
  sleep 0.5
done
if [[ "$FE_OK" -ne 1 ]]; then
  warn "Frontend not ready yet — see $LOG_DIR/frontend.log"
else
  ok "Frontend ready"
fi

echo
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  ChordLens is running${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "  App:     ${CYAN}http://localhost:3000${NC}"
echo -e "  API:     ${CYAN}http://localhost:8000${NC}"
echo -e "  Health:  ${CYAN}http://localhost:8000/health${NC}"
echo
echo -e "  Logs:    ${YELLOW}.run/logs/{api,worker,frontend}.log${NC}"
echo -e "  Stop:    ${YELLOW}Ctrl+C${NC}  or  ${YELLOW}./start.sh --stop${NC}"
echo

# stream logs (optional) — keep process alive
tail -n 0 -F "$LOG_DIR/api.log" "$LOG_DIR/worker.log" "$LOG_DIR/frontend.log" 2>/dev/null &
TAIL_PID=$!

# wait until any child dies or user hits Ctrl+C
wait "$(cat "$PID_DIR/api.pid")" "$(cat "$PID_DIR/worker.pid")" "$(cat "$PID_DIR/frontend.pid")" 2>/dev/null || true
kill $TAIL_PID 2>/dev/null || true
stop_all
