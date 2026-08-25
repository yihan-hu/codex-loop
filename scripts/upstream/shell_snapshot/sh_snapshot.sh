if [ -n "$ENV" ] && [ -r "$ENV" ]; then
  . "$ENV"
fi
echo '# Snapshot file'
echo '# Unset all aliases to avoid conflicts with functions'
unalias -a 2>/dev/null || true
echo '# Functions'
if command -v typeset >/dev/null 2>&1; then
  typeset -f
elif command -v declare >/dev/null 2>&1; then
  declare -f
fi
echo ''
if set -o >/dev/null 2>&1; then
  sh_opts=$(set -o | awk '$2=="on"{print $1}')
  sh_opt_count=$(printf '%s\n' "$sh_opts" | sed '/^$/d' | wc -l | tr -d ' ')
  echo "# setopts $sh_opt_count"
  if [ -n "$sh_opts" ]; then
    printf 'set -o %s\n' $sh_opts
  fi
else
  echo '# setopts 0'
fi
echo ''
if alias >/dev/null 2>&1; then
  alias_count=$(alias | wc -l | tr -d ' ')
  echo "# aliases $alias_count"
  alias
  echo ''
else
  echo '# aliases 0'
fi
# Capture exported variables
if export -p >/dev/null 2>&1; then
  export_lines=$(export -p | awk '
/^(export|declare -x|typeset -x) / {
  line=$0
  name=line
  sub(/^(export|declare -x|typeset -x) /, "", name)
  sub(/=.*/, "", name)
  if (name ~ /^(PWD|OLDPWD)$/) {
    next
  }
  if (name ~ /^[A-Za-z_][A-Za-z0-9_]*$/) {
    print line
  }
}')
  export_count=$(printf '%s\n' "$export_lines" | sed '/^$/d' | wc -l | tr -d ' ')
  echo "# exports $export_count"
  if [ -n "$export_lines" ]; then
    printf '%s\n' "$export_lines"
  fi
else
  export_count=$(env | sort | awk -F= '$1 ~ /^[A-Za-z_][A-Za-z0-9_]*$/ { count++ } END { print count }')
  echo "# exports $export_count"
  env | sort | while IFS='=' read -r key value; do
    case "$key" in
      ""|[0-9]*|*[!A-Za-z0-9_]*|PWD|OLDPWD) continue ;;
    esac
    escaped=$(printf "%s" "$value" | sed "s/'/'\"'\"'/g")
    printf "export %s='%s'\n" "$key" "$escaped"
  done
fi
