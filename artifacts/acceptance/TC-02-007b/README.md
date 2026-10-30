# PostgreSQL readiness repair evidence

Base: `da6d6eedb8c256d1e5e775fcfdf8b1a3250f34bb`.
Claim: [#85 / 6516745030](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6516745030).

## Observed failure

[PR #138 run 41015331271, build job 123930270947](https://github.com/Johnathan-u/trust-copilot/actions/runs/41015331271/job/123930270947)
was inspected through the decoded job log. Relevant entries:

```text
06:40:20.9302730Z Digest: sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a
06:40:20.9303861Z Status: Downloaded newer image for pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a
06:40:24.3367819Z [container identifier returned]
06:40:25.7468681Z /var/run/postgresql:5432 - rejecting connections
06:40:25.7521103Z Process completed with exit code 1.
```

Both probe commands in that job omitted `-h`. The loop could not exhaust its
60 one-second retries in that interval; it exited on a successful socket probe,
then the required final socket probe rejected. No backend test ran in that job.

## Primary source diagnosis

Sources read on 2026-10-30:

- [pgvector v0.8.7 Dockerfile](https://github.com/pgvector/pgvector/blob/v0.8.7/Dockerfile)
  uses the official PostgreSQL image through `PG_MAJOR`/Debian arguments and does
  not replace its entrypoint.
- [Official PostgreSQL 16 bookworm Dockerfile](https://github.com/docker-library/postgres/blob/master/16/bookworm/Dockerfile)
  currently specifies PostgreSQL 16.15 and copies the official entrypoint.
- [Official docker-entrypoint.sh](https://github.com/docker-library/postgres/blob/master/docker-entrypoint.sh)
  starts `docker_temp_server_start` with `listen_addresses=''`, runs database
  initialization, calls `docker_temp_server_stop` with a fast stop, then executes
  the final PostgreSQL process. This is the socket-only bootstrap mechanism.
- [PostgreSQL 16 pg_isready documentation](https://www.postgresql.org/docs/16/app-pg-isready.html)
  documents host selection and success/rejection/no-response exit statuses.

These upstream sources explain the lifecycle; they do not prove a byte-for-byte
mapping from the pinned digest to a particular upstream revision. No local image
was pulled, inspected or run: Docker and Podman are unavailable. The job log and
executable simulation are kept distinct from real-container qualification.

## Executable controls

`test_ci_postgres_readiness.py` reads the actual startup step from `ci.yml` and
executes its shell. Temporary fake command executables model only readiness
states; Docker is never invoked. Their state records contain transport, lifecycle
phase, status, probe count and sleep count, not password arguments.

| Scenario                                       | Required result                                       | Probes | Simulated sleeps |
| ---------------------------------------------- | ----------------------------------------------------- | -----: | ---------------: |
| Socket bootstrap → shutdown → final TCP server | Exit 0; export matching URLs only after final success |      5 |                3 |
| Already ready                                  | Exit 0; final probe still executes                    |      2 |                0 |
| Never ready                                    | Exit 2; no URLs exported                              |     61 |               60 |
| Ready loop, rejecting final probe              | Exit 1; no URLs exported                              |      2 |                0 |

The unchanged workflow is red: 4 failures, including exit 1 during the bootstrap
scenario. Adding the TCP host makes all four controls pass. Temporary negative
controls remove the final probe or change the loop bound to 61; each selected
regression fails. Those mutations are restored and are not part of the commit.

Workflow preservation is also checked byte-for-byte: removing only the two added
host arguments and two comment lines reproduces the base workflow exactly.
Image/digest, isolation, credentials, retry limit, final-check requirement,
dependencies, artifact uploads and all other checks remain unchanged.

See `verification.txt` for commands and results. Independent review and all four
exact-head CI jobs remain necessary; no local Docker/PostgreSQL success is claimed.
