#!/bin/bash
rm -rf venv
python -m venv venv
source venv/bin/activate  # or venv\\Scripts\\activate on Windows
pip install pandas
