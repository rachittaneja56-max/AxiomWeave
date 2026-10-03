# Phase 2 retrieval benchmark

`phase2_fixtures.json` is the predeclared synthetic fixture set. Its independent
case unit is a SourcePack; it contains four packs and six tasks. R0 is the
matched full-context baseline for every pack.

The measured PostgreSQL native FTS result is in
`phase2_benchmark_result.json`. At top-2 it recalled 2/7 required regions and
1/4 qualifier regions. R0 exposed 7/7 required and 4/4 qualifier regions.
FTS used 117 of R0's 785 source-region characters, an 85.1% reduction, but its
coverage is poor on this fixture set. The profile remains `CANDIDATE` and is
**not promoted**.

The FTS run used PostgreSQL 17 and pgvector 0.8.6 with PostgreSQL's `simple`
configuration. It took 10.19 ms per query on average over six loopback queries;
this is a local measurement, not a production latency estimate. Character
counts include original region text only; they exclude role labels and provider
schema overhead.

Exact pgvector and reciprocal-rank fusion tests verify mechanics only. No
approved semantic embedding profile was evaluated, so vector and hybrid quality
remain not evaluated. Generated-output quality and factuality were not tested.
