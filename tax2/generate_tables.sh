#!/bin/bash

source venv/bin/activate

python cli.py rules/federal/2025.yaml \
  --filing-status single \
  --inc-max 500000 \
  --step 50 \
  --out tables/federal_2025.parquet

python cli.py rules/states/GA/2025.yaml \
  --filing-status single \
  --inc-max 500000 \
  --step 50 \
  --out tables/ga_2025.parquet

python3 merge_tables.py

