#!/bin/sh
# 60/30/10 color budget guard. Run from anywhere: sh frontend/scripts/check-color-budget.sh
cd "$(dirname "$0")/.." || exit 2
fail=0

count() {
  grep -rhoE "$1" src --include=*.ts --include=*.tsx --include=*.css 2>/dev/null | wc -l | tr -d ' '
}

check() {
  n=$(count "$2")
  if [ "$n" -gt "$3" ]; then
    echo "FAIL $1: $n > $3"
    fail=1
  else
    echo "ok   $1: $n <= $3"
  fi
}

count_ts() {
  grep -rhoE "$1" src --include=*.ts --include=*.tsx 2>/dev/null | wc -l | tr -d ' '
}

check_ts() {
  n=$(count_ts "$2")
  if [ "$n" -gt "$3" ]; then
    echo "FAIL $1: $n > $3"
    fail=1
  else
    echo "ok   $1: $n <= $3"
  fi
}

check "text-accent (incl. hover)"   '\btext-accent([^-a-z0-9/]|$)'          45
check "border-accent"               '\bborder-accent(/[0-9]+)?\b'            25
check "solid bg-accent"             '\bbg-accent([^-a-z0-9/]|$)'             15
check "bg-accent/NN tints"          'bg-accent/[0-9]+'                        0
check "accent-2"                    'accent-2'                                0
check "undefined vars"              'var\(--(text-muted|border-line)\)'       0
check "status opacity fills"        'bg-(good|bad|warn|info)/[0-9]+'          0
check "status -bg tints (badges)"   'bg-(good|bad|warn|info)-bg'             45
# restyle guards (must stay 0)
check "arbitrary hex classes"       '\-\[#[0-9a-fA-F]{3,8}\]'                 0
check "dark: variants"              '(^|[ "'"'"'`])dark:'                     0

# extended guards (Fix 4)
check "white rgba literals"         'rgba\(255, ?255, ?255'                  0
check_ts "raw rgba in ts/tsx"       'rgba\([0-9]'                             0
check "white/black borders+dividers" '\b(border|divide)-(white|black)'       0
check "bg-white tints"              '\bbg-white/'                             0
check "faint on structure (App)"    'text-faint">\{hint'                      0

exit $fail
