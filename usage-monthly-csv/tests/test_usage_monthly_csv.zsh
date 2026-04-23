#!/usr/bin/env zsh
set -euo pipefail

SCRIPT=/Users/kevinharlan/source/utilities/usage-monthly-csv/usage-monthly-csv
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
mkdir -p "$TMPDIR/bin" "$TMPDIR/out"

cat <<'STUB' >"$TMPDIR/bin/ccusage_csv"
#!/usr/bin/env zsh
set -eu
print -- "ccusage:$*"
STUB

cat <<'STUB' >"$TMPDIR/bin/cusage_csv"
#!/usr/bin/env zsh
set -eu
print -- "cusage:$*"
STUB

chmod +x "$TMPDIR/bin/ccusage_csv" "$TMPDIR/bin/cusage_csv"

export PATH="$TMPDIR/bin:$PATH"

fail() {
  print -u2 -- "FAIL: $*"
  exit 1
}

expect_file_contains() {
  local file=$1
  local pattern=$2
  [[ -f "$file" ]] || fail "missing file $file"
  grep -F -- "$pattern" "$file" >/dev/null || fail "expected '$pattern' in $file"
}

expect_file_not_contains() {
  local file=$1
  local pattern=$2
  [[ -f "$file" ]] || fail "missing file $file"
  if grep -F -- "$pattern" "$file" >/dev/null; then
    fail "did not expect '$pattern' in $file"
  fi
}

zsh "$SCRIPT" --date 2026-04-10 --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" "ccusage:--since 20260401"
expect_file_contains "$TMPDIR/out/cusage-0426.csv" "cusage:--since 20260401"
[[ ! -e "$TMPDIR/out/ccusage-0326.csv" ]] || fail "unexpected prior-month ccusage file"
[[ ! -e "$TMPDIR/out/cusage-0326.csv" ]] || fail "unexpected prior-month cusage file"

rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-05-02 --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-0526.csv" "ccusage:--since 20260501"
expect_file_contains "$TMPDIR/out/cusage-0526.csv" "cusage:--since 20260501"
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" "ccusage:--since 20260401"
expect_file_contains "$TMPDIR/out/cusage-0426.csv" "cusage:--since 20260401"

rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-01-10 --prior-month --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-1225.csv" "ccusage:--since 20251201"
expect_file_contains "$TMPDIR/out/cusage-1225.csv" "cusage:--since 20251201"
[[ ! -e "$TMPDIR/out/ccusage-0126.csv" ]] || fail "unexpected current-month ccusage file"
[[ ! -e "$TMPDIR/out/cusage-0126.csv" ]] || fail "unexpected current-month cusage file"

rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-06-20 --output-dir "$TMPDIR/custom"
expect_file_contains "$TMPDIR/custom/ccusage-0626.csv" "ccusage:--since 20260601"
expect_file_contains "$TMPDIR/custom/cusage-0626.csv" "cusage:--since 20260601"

cat <<'STUB' >"$TMPDIR/bin/ccusage_csv"
#!/usr/bin/env zsh
set -eu
cat <<'EOF'
"date","inputTokens","outputTokens","cacheCreationTokens","cacheReadTokens","totalTokens","totalCost"
"2026-04-01",1,2,3,4,5,6
EOF
STUB

cat <<'STUB' >"$TMPDIR/bin/cusage_csv"
#!/usr/bin/env zsh
set -eu
cat <<'EOF'
"date","inputTokens","cachedInputTokens","outputTokens","reasoningOutputTokens","totalTokens","costUSD"
"Apr 01, 2026",10,20,30,40,50,60
EOF
STUB

chmod +x "$TMPDIR/bin/ccusage_csv" "$TMPDIR/bin/cusage_csv"
rm -f "$TMPDIR/out"/*.csv(N)

zsh "$SCRIPT" --date 2026-04-10 --output-dir "$TMPDIR/out"
expect_file_contains "$TMPDIR/out/ccusage-0426.csv" '"2026-04-01",1,2,3,4,5,6'
expect_file_contains "$TMPDIR/out/cusage-0426.csv" '"2026-04-01",10,20,30,40,50,60'
expect_file_not_contains "$TMPDIR/out/cusage-0426.csv" '"Apr 01, 2026",10,20,30,40,50,60'

HELP=$(zsh "$SCRIPT" --help)
print -- "$HELP" | grep -F -- '--output-dir DIR' >/dev/null || fail 'help missing output-dir'
print -- "$HELP" | grep -F -- '--prior-month' >/dev/null || fail 'help missing prior-month'
print -- "$HELP" | grep -F -- 'Defaults:' >/dev/null || fail 'help missing defaults section'
print -- "$HELP" | grep -F -- '2 days' >/dev/null || fail 'help missing boundary default'

TMPROOT=$(mktemp -d)
trap 'rm -rf "$TMPDIR" "$TMPROOT"' EXIT
mkdir -p "$TMPROOT/home" "$TMPROOT/out"

cat <<'ZSHRC' >"$TMPROOT/home/.zshrc"
ccusage_csv() {
  print -- "ccusage:$*"
}

cusage_csv() {
  print -- "cusage:$*"
}
ZSHRC

HOME="$TMPROOT/home" PATH="/usr/bin:/bin:/usr/sbin:/sbin" zsh "$SCRIPT" --date 2026-04-10 --output-dir "$TMPROOT/out"
expect_file_contains "$TMPROOT/out/ccusage-0426.csv" "ccusage:--since 20260401"
expect_file_contains "$TMPROOT/out/cusage-0426.csv" "cusage:--since 20260401"

print -- 'ok'
