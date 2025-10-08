#!/bin/bash

rm -rf venv
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install streamlit pandas requests


