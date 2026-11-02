# Local load test report

## Target and setup

Before testing, the project set a service-level objective of p95 review submission-to-terminal-result latency below 30 seconds at five concurrent users. Locust's `review submit-to-result` measurement starts before submission and ends after the review reaches a terminal state. The local deterministic stub used a 0.1-second delay per model step. These are local development runs, not production capacity measurements.

## Results

| Workers | Concurrent users | Completed workflows | Locust failures | p50 | p95 | Throughput |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 51 | 0 | 3.9 s | 4.2 s | 1.18 workflows/s |
| 3 | 5 | 156 | 0 | 1.0 s | 1.3 s | 3.54 workflows/s |
| 3 | 120 | 107 | 0 | 13.0 s | 25.0 s | 3.56 workflows/s |

The five-user three-worker run completed roughly 3 times as many workflows per second as the one-worker run and had 69% lower p95 latency. The 120-user run stayed under the 30-second p95 target, with only 5 seconds of headroom. It is a single short run; it does not establish a safe production concurrency limit. A zero Locust failure count also does not cover container restarts or provider outages.

The Locust `WORKFLOW` rows in [one-worker_stats.csv](load-results/one-worker_stats.csv), [three-workers_stats.csv](load-results/three-workers_stats.csv), and [three-workers-120-users_stats.csv](load-results/three-workers-120-users_stats.csv) contain the raw values. Each run used a 45-second observation window. Test runs used the local Python API and SQLite-backed worker processes on one host; Docker Compose could not be started because this machine has no reachable Docker daemon. The 120-user run generated 12,392 status polls, so API request throughput should not be confused with completed-review throughput.

## Limits

- Results use a deterministic stub, not a hosted model, so provider latency, rate limits, and cost are not represented.
- The corpus and workflow return retrieval evidence and route all cases to human review; this does not measure legal decision accuracy.
- The local SQLite database and single-host setup differ from a production queue and distributed workers.
- Compose syntax was validated, but image builds, service health checks, and container networking remain unverified on this host.
