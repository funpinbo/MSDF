-- MSDF 메타데이터 스키마. 실제 데이터는 Resolver 쪽에 있고 여기에는 메타데이터만 있다.

CREATE TABLE IF NOT EXISTS artifact (
  id           TEXT PRIMARY KEY,      -- Resolver가 발급 (Planner의 planned_id와 같아야 한다)
  lineage_key  TEXT NOT NULL,         -- 출력 슬롯의 정체
  step_key     TEXT NOT NULL,         -- 만든 생산 단계의 정체
  generation   REAL NOT NULL,         -- Planner가 고정
  service      TEXT NOT NULL,
  action       TEXT NOT NULL,
  slot         TEXT NOT NULL,
  version      TEXT NOT NULL,
  order_params TEXT,                  -- 루트 단계만 (JSON)
  backend      TEXT NOT NULL,         -- 저장한 백엔드 설정 (JSON). 다른 서비스가 읽을 때 쓴다
  location     TEXT,
  checksum     TEXT,
  nbytes       INTEGER,
  created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lineage ON artifact(lineage_key, created_at);
CREATE INDEX IF NOT EXISTS idx_artifact_step ON artifact(step_key, generation);

CREATE TABLE IF NOT EXISTS artifact_edge (
  parent_id TEXT NOT NULL,
  child_id  TEXT NOT NULL,
  slot      TEXT NOT NULL,            -- child를 만든 Action의 입력 슬롯
  PRIMARY KEY (child_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_edge_parent ON artifact_edge(parent_id);

CREATE TABLE IF NOT EXISTS artifact_tombstone (
  artifact_id  TEXT PRIMARY KEY,
  deleted_at   REAL NOT NULL,
  reason       TEXT,                  -- requested | lost
  account      TEXT,
  service      TEXT,
  cascade_root TEXT,
  body_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run (
  run_id          TEXT PRIMARY KEY,
  order_name      TEXT NOT NULL,
  requester       TEXT NOT NULL,
  params          TEXT NOT NULL,      -- JSON
  context         TEXT NOT NULL,      -- JSON (감사 추적용, 해시에는 넣지 않음)
  result_lineage  TEXT,
  result_artifact TEXT,
  status          TEXT NOT NULL,      -- running | done | failed
  replans         INTEGER NOT NULL DEFAULT 0,
  plan            TEXT,               -- {"steps": [노드], "cached": [노드], "joined": [노드]} (JSON)
  meta            TEXT,               -- 요청한 쪽이 붙인 correlation metadata (JSON). cache key에 들어가지 않음
  idempotency_key TEXT,               -- 요청한 쪽이 정한 키. 같은 requester + 키면 run을 새로 만들지 않음
  subscription_id TEXT,               -- 구독에 속한 run이면 처음 요청의 run_id (= 배달되는 request_id)
  refresh_no      INTEGER NOT NULL DEFAULT 0,  -- 0 = 처음 요청, 1, 2, ... = source가 바뀌어 다시 계산한 것
  error           TEXT,
  created_at      REAL NOT NULL,
  finished_at     REAL
);

CREATE TABLE IF NOT EXISTS step (
  run_id      TEXT NOT NULL,
  step_no     INTEGER NOT NULL,
  kind        TEXT NOT NULL,          -- produce | deliver | deliver_fail
  node        TEXT,
  service     TEXT NOT NULL,
  action      TEXT NOT NULL,
  step_key    TEXT,                   -- produce만
  generation  REAL,
  version     TEXT,
  inputs      TEXT NOT NULL DEFAULT '{}',   -- 슬롯 → artifact_id (JSON)
  params      TEXT NOT NULL DEFAULT '{}',   -- 루트 produce만 (JSON)
  outputs     TEXT NOT NULL DEFAULT '{}',   -- 슬롯 → {lineage_key, artifact_id} (JSON)
  deps        TEXT NOT NULL DEFAULT '[]',   -- ["run_id:step_no", ...]
  waiting     INTEGER NOT NULL DEFAULT 0,   -- 아직 끝나지 않은 deps 수. 0이면 실행할 수 있다
  fail_status TEXT,                   -- deliver_fail: failed | cancelled
  status      TEXT NOT NULL,          -- queued|leased|running|saved|done|failed|cancelled
  worker      TEXT,
  lease_until REAL,
  attempts    INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 0,
  retry_delay REAL NOT NULL DEFAULT 0,
  not_before  REAL NOT NULL DEFAULT 0,
  error       TEXT,
  queued_at   REAL,
  started_at  REAL,
  saved_at    REAL,
  done_at     REAL,
  PRIMARY KEY (run_id, step_no)
);
CREATE INDEX IF NOT EXISTS idx_step_status ON step(status);
-- ready(): 실행할 수 있는 단계만 바로 찾는다 (큐 전체를 읽지 않는다)
CREATE INDEX IF NOT EXISTS idx_step_ready ON step(status, waiting, service, queued_at);

-- 단계 사이 의존 관계. 단계가 끝나면 이 표로 기다리던 단계를 찾아 waiting을 줄인다
CREATE TABLE IF NOT EXISTS step_dep (
  run_id  TEXT NOT NULL,
  step_no INTEGER NOT NULL,
  dep     TEXT NOT NULL,                 -- 기다리는 단계 "run_id:step_no"
  PRIMARY KEY (run_id, step_no, dep)
);
CREATE INDEX IF NOT EXISTS idx_step_dep ON step_dep(dep);
CREATE INDEX IF NOT EXISTS idx_step_queued ON step(queued_at);
CREATE INDEX IF NOT EXISTS idx_run_created ON run(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_idempotency ON run(requester, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
-- 같은 단계를 두 번 동시에 만들지 않는다. 끝난 단계는 제약에서 빠진다.
CREATE UNIQUE INDEX IF NOT EXISTS idx_inflight ON step(step_key)
  WHERE kind = 'produce' AND status IN ('queued', 'leased', 'running', 'saved');

-- 데이터 주인 서비스가 invalidate()로 알린 source 데이터의 버전. step_key의 재료가 된다.
-- scope = '*' (그 Action 전체) 또는 params의 해시 (그 params로 만든 것만)
CREATE TABLE IF NOT EXISTS source_version (
  service    TEXT NOT NULL,
  action     TEXT NOT NULL,
  scope      TEXT NOT NULL,
  params     TEXT,                  -- scope가 params일 때 원래 값 (JSON, 보기용)
  version    TEXT NOT NULL,
  changed_at REAL NOT NULL,
  PRIMARY KEY (service, action, scope)
);

-- subscribe: 결과가 기대는 source가 invalidate()되면 같은 요청을 다시 계산해 다시 배달한다
CREATE TABLE IF NOT EXISTS subscription (
  request_id      TEXT PRIMARY KEY,   -- 처음 요청의 run_id. refresh도 이 값으로 배달한다
  order_name      TEXT NOT NULL,
  requester       TEXT NOT NULL,
  params          TEXT NOT NULL,      -- JSON
  context         TEXT NOT NULL,      -- JSON. refresh마다 IAM을 이 값으로 다시 검사한다
  meta            TEXT,               -- JSON
  sources         TEXT NOT NULL,      -- [[service, action, scope], ...] 결과가 기대는 source
  status          TEXT NOT NULL,      -- active | ended
  ended_reason    TEXT,               -- expired | cancelled | denied | dag_changed
  created_at      REAL NOT NULL,
  expires_at      REAL,               -- NULL이면 만료 없음
  dirty           INTEGER NOT NULL DEFAULT 0,  -- source가 바뀌어 다시 계산해야 함
  active_run      TEXT,               -- 지금 도는 refresh run (한 번에 하나)
  refresh_count   INTEGER NOT NULL DEFAULT 0,
  last_refresh_at REAL,
  last_delivered  TEXT,               -- 마지막으로 배달한 결과 artifact_id
  last_checksum   TEXT,               -- 그 결과의 checksum. 같으면 다시 배달하지 않는다
  idle_since      REAL                -- 요청 서비스가 연결되어 있지 않게 된 시각 (돌아오면 NULL)
);
CREATE INDEX IF NOT EXISTS idx_subscription_status ON subscription(status);
