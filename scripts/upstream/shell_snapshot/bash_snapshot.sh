if [ -z "$BASH_ENV" ] && [ -r "$HOME/.bashrc" ]; then
  . "$HOME/.bashrc"
fi
echo '# Snapshot file'
echo '# Unset all aliases to avoid conflicts with functions'
unalias -a 2>/dev/null || true
echo '# Functions'
declare -f
echo ''
bash_opts=$(set -o | awk '$2=="on"{print $1}')
bash_opt_count=$(printf '%s\n' "$bash_opts" | sed '/^$/d' | wc -l | tr -d ' ')
echo "# setopts $bash_opt_count"
if [ -n "$bash_opts" ]; then
  printf 'set -o %s\n' $bash_opts
fi
echo ''
alias_count=$(alias -p | wc -l | tr -d ' ')
echo "# aliases $alias_count"
alias -p
echo ''
# Capture exported variables
export_lines=$(
  while IFS= read -r name; do
    if [[ "$name" =~ ^(PWD|OLDPWD)$ ]]; then
      continue
    fi
    if [[ ! "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    declare -xp "$name" 2>/dev/null || true
  done < <(compgen -e)
)
export_count=$(printf '%s\n' "$export_lines" | sed '/^$/d' | wc -l | tr -d ' ')
echo "# exports $export_count"
if [ -n "$export_lines" ]; then
  printf '%s\n' "$export_lines"
fi
