"""lib - shared library for the conversation-history integrity runners (EXP-1..EXP-7)."""

import csv

# Unified batches carry full raw model outputs (GLM sessions ~90K chars per
# row); the default csv field limit (131072) crashes readers on long rows.
# Set once process-wide; applies to every batch reader in the runners,
# resume, judge, and tables.
csv.field_size_limit(2**31 - 1)
