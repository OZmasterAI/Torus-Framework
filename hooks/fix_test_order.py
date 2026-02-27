#!/usr/bin/env python3
"""Fix test_framework.py: move Self-Evolution section before SUMMARY block.

The Self-Evolution section ended up after sys.exit() due to a previous restructure.
This script moves it back before the SUMMARY.
"""
import sys

fpath = '~/.claude/hooks/test_framework.py'
with open(fpath, 'r') as f:
    lines = f.readlines()

total = len(lines)

# Find sys.exit line (the final FAIL==0 one)
sysexit_idx = None
for i, line in enumerate(lines):
    if 'sys.exit(0 if FAIL' in line:
        sysexit_idx = i

if sysexit_idx is None:
    print("ERROR: sys.exit not found")
    sys.exit(1)
print(f"sys.exit at line {sysexit_idx + 1}")

# Find the SUMMARY section start
summary_start = None
for i in range(sysexit_idx, max(0, sysexit_idx - 20), -1):
    if '# SUMMARY' in lines[i]:
        summary_start = i
        break

if summary_start is None:
    print("ERROR: SUMMARY not found")
    sys.exit(1)
print(f"SUMMARY at line {summary_start + 1}")

# Find Self-Evolution section after sys.exit
selfevo_start = None
for i in range(sysexit_idx + 1, total):
    line = lines[i].strip()
    if '# Test: Self-Evolution' in line or 'Self-Evolution: State Pruning' in line:
        selfevo_start = i
        while selfevo_start > sysexit_idx + 1 and lines[selfevo_start - 1].strip() in ('', '#'):
            selfevo_start -= 1
        break

if selfevo_start is None:
    print("No Self-Evolution after sys.exit — already correct, nothing to fix")
    sys.exit(0)
print(f"Self-Evolution at line {selfevo_start + 1}")

selfevo_block = lines[selfevo_start:]

new_lines = (
    lines[:summary_start]
    + ['\n']
    + selfevo_block
    + ['\n']
    + lines[summary_start:selfevo_start]
)

with open(fpath, 'w') as f:
    f.writelines(new_lines)

print(f"Done. Total lines: {len(new_lines)}")
