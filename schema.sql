-- PostgreSQL / PostGIS starter schema

create extension if not exists postgis;
create extension if not exists pgcrypto;

create table entrances (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  approach_name text not null,
  gate_location geography(point, 4326) not null,
  approach_start geography(point, 4326) not null,
  timezone text not null default 'America/Los_Angeles',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table traffic_snapshots (
  id bigserial primary key,
  entrance_id uuid not null references entrances(id),
  observed_at timestamptz not null,
  traffic_duration_seconds integer not null,
  google_historical_duration_seconds integer not null,
  free_flow_baseline_seconds integer not null,
  derived_delay_seconds integer not null,
  route_version text not null,
  distance_meters integer,
  provider text not null,
  provider_observation_id text,
  raw_payload jsonb,
  created_at timestamptz not null default now()
);
create index traffic_snapshots_entrance_time_idx
  on traffic_snapshots (entrance_id, observed_at desc);

create table traffic_polyline_snapshots (
  id bigserial primary key,
  entrance_id uuid not null references entrances(id),
  observed_at timestamptz not null,
  route_version text not null,
  distance_meters integer,
  queue_start geography(point, 4326),
  queue_distance_meters integer,
  slow_distance_meters integer not null default 0,
  jam_distance_meters integer not null default 0,
  congestion_start_index integer,
  congestion_end_index integer,
  encoded_polyline text,
  speed_intervals jsonb not null,
  raw_payload jsonb,
  created_at timestamptz not null default now()
);
create index traffic_polyline_entrance_time_idx
  on traffic_polyline_snapshots (entrance_id, observed_at desc);

create table condition_events (
  id bigserial primary key,
  entrance_id uuid references entrances(id),
  source text not null,
  source_event_id text,
  event_type text not null,
  severity text not null,
  title text not null,
  description text,
  starts_at timestamptz,
  ends_at timestamptz,
  geometry geography(geometry, 4326),
  is_active boolean not null default true,
  raw_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table wait_reports (
  id uuid primary key default gen_random_uuid(),
  entrance_id uuid not null references entrances(id),
  anonymous_session_hash text,
  device_hash text,
  report_secret_hash text,
  started_at timestamptz not null,
  completed_at timestamptz,
  wait_seconds integer,
  queue_entry_location geography(point, 4326),
  queue_entry_accuracy_meters real,
  queue_distance_to_gate_meters integer,
  completion_method text,
  confirmation_status text not null default 'pending',
  quality_score smallint,
  client_metadata jsonb,
  created_at timestamptz not null default now()
);
create index wait_reports_entrance_completed_idx
  on wait_reports (entrance_id, completed_at desc)
  where completed_at is not null;

create table wait_estimates (
  id bigserial primary key,
  entrance_id uuid not null references entrances(id),
  estimated_at timestamptz not null,
  valid_until timestamptz not null,
  low_minutes smallint not null,
  median_minutes smallint not null,
  high_minutes smallint not null,
  queue_distance_miles numeric(4,1),
  trend text not null,
  confidence_score smallint not null check (confidence_score between 0 and 100),
  confidence_level text not null,
  recent_report_count smallint not null default 0,
  traffic_delay_seconds integer,
  basis jsonb not null,
  model_version text not null,
  created_at timestamptz not null default now()
);
create index wait_estimates_entrance_time_idx
  on wait_estimates (entrance_id, estimated_at desc);

create table hourly_forecasts (
  id bigserial primary key,
  entrance_id uuid not null references entrances(id),
  forecast_for timestamptz not null,
  generated_at timestamptz not null,
  low_minutes smallint not null,
  median_minutes smallint not null,
  high_minutes smallint not null,
  confidence_score smallint not null,
  model_version text not null,
  features jsonb,
  unique (entrance_id, forecast_for, model_version)
);


create table feedback_submissions (
  id uuid primary key default gen_random_uuid(),
  feedback_type text not null,
  category text not null,
  entrance_id uuid references entrances(id),
  displayed_low_minutes smallint,
  displayed_high_minutes smallint,
  displayed_observed_at timestamptz,
  actual_wait_minutes smallint,
  gate_arrival_at timestamptz,
  message text,
  contact_email text,
  site_version text not null,
  page_path text,
  anonymous_client_hash text,
  status text not null default 'new',
  reviewed_at timestamptz,
  resolution_notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index feedback_status_created_idx
  on feedback_submissions (status, created_at desc);
