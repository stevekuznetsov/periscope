CREATE TYPE job_type AS ENUM (
  'periodic',
  'presubmit',
  'postsubmit',
  'batch'
);

CREATE TABLE builds (
  id SERIAL PRIMARY KEY UNIQUE,
  job TEXT NOT NULL,
  build TEXT NOT NULL,
  type job_type NOT NULL
);

CREATE TABLE repos (
  id INTEGER PRIMARY KEY UNIQUE NOT NULL,
  FOREIGN KEY (id) REFERENCES builds(id),
  org TEXT NOT NULL,
  repo TEXT NOT NULL,
  ref TEXT NOT NULL,
  sha CHAR(40) NOT NULL
);

CREATE TABLE pulls (
  id INTEGER PRIMARY KEY NOT NULL,
  FOREIGN KEY (id) REFERENCES builds(id),
  pull INTEGER NOT NULL,
  sha CHAR(40) NOT NULL
);

CREATE TABLE junit_summaries (
  id INTEGER PRIMARY KEY UNIQUE NOT NULL,
  FOREIGN KEY (id) REFERENCES builds(id),
  succeeded INTEGER NOT NULL,
  skipped INTEGER NOT NULL,
  failed INTEGER NOT NULL
);

CREATE TABLE junit_failures (
  id INTEGER PRIMARY KEY NOT NULL,
  FOREIGN KEY (id) REFERENCES builds(id),
  name TEXT NOT NULL,
  duration INTEGER,
  output TEXT,
  stdout TEXT,
  stderr TEXT
);

CREATE TABLE storage (
  id INTEGER PRIMARY KEY UNIQUE NOT NULL,
  FOREIGN KEY (id) REFERENCES builds(id),
  url TEXT NOT NULL
);