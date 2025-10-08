#!/bin/bash

python3 -m venv venv
source venv/bin/activate
pip install pandas openpyxl xlsxwriter

# to run
# python md_converter.py
