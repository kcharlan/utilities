#!/usr/bin/env python3
import sys
from pathlib import Path

task_path = Path(sys.argv[1])

print("##PROGRESS## wrong-task | Phase: reading | 1/5", flush=True)
print("##PROGRESS## 039 | Phase: implementing | 3/5", flush=True)
print("##PROGRESS## wrong-task | Detail: should be ignored", flush=True)
print("##PROGRESS## 039 | Detail: canonical detail", flush=True)
task_path.with_name(task_path.name.removesuffix(".plan.md") + ".status").write_text(
    "STATUS: done\n"
    "COMMITS: none\n"
    "TESTS_RAN: none\n"
    "TEST_RESULT: skip\n",
    encoding="utf-8",
)
