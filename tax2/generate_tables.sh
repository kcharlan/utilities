#!/bin/bash

source venv/bin/activate

python cli.py --rules rules/federal/2026.yaml \
  --filing-status single \
  --inc-max 500000 \
  --step 50 \
  --out tables/federal_2026.parquet

python cli.py --rules rules/states/GA/2026.yaml \
  --filing-status single \
  --inc-max 500000 \
  --step 50 \
  --out tables/ga_2026.parquet

python3 merge_tables.py

