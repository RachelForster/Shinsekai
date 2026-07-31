#!/usr/bin/env bash

# Shared path boundary for the POSIX launch and install scripts.  The caller
# must set PROJECT_ROOT to a physical, absolute project directory first.

shinsekai_portable_environment_name() {
  local value="$1"
  local stem

  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ &&
     "$value" != *. ]] || return 1
  stem="${value%%.*}"
  case "$stem" in
    [Cc][Oo][Nn] | [Pp][Rr][Nn] | [Aa][Uu][Xx] | [Nn][Uu][Ll] | \
      [Cc][Oo][Mm][1-9] | [Ll][Pp][Tt][1-9])
      return 1
      ;;
  esac
}

shinsekai_absolute_path_is_exact() {
  local absolute_path="$1"
  local cursor=""
  local component
  local -a components

  [[ -n "$absolute_path" && "$absolute_path" == /* &&
     "$absolute_path" != "/" && "$absolute_path" != *\\* &&
     "$absolute_path" != *$'\n'* && "$absolute_path" != *$'\r'* &&
     "$absolute_path" != *$'\t'* ]] || return 1
  IFS="/" read -r -a components <<< "$absolute_path"
  for component in "${components[@]}"; do
    [[ -z "$component" && -z "$cursor" ]] && continue
    [[ -n "$component" && "$component" != "." && "$component" != ".." ]] || return 1
    cursor="$cursor/$component"
  done
}

shinsekai_absolute_path_has_no_links() {
  local absolute_path="$1"
  local cursor=""
  local component
  local -a components

  shinsekai_absolute_path_is_exact "$absolute_path" || return 1
  IFS="/" read -r -a components <<< "$absolute_path"
  for component in "${components[@]}"; do
    [[ -z "$component" && -z "$cursor" ]] && continue
    cursor="$cursor/$component"
    [[ ! -L "$cursor" ]] || return 1
  done
}

shinsekai_absolute_file_is_real() {
  local absolute_path="$1"
  shinsekai_absolute_path_has_no_links "$absolute_path" &&
    [[ -f "$absolute_path" ]]
}

shinsekai_absolute_directory_is_real() {
  local absolute_path="$1"
  shinsekai_absolute_path_has_no_links "$absolute_path" &&
    [[ -d "$absolute_path" ]]
}

shinsekai_absolute_directory_is_real_or_missing() {
  local absolute_path="$1"
  shinsekai_absolute_path_has_no_links "$absolute_path" || return 1
  if [[ -e "$absolute_path" || -L "$absolute_path" ]]; then
    [[ -d "$absolute_path" && ! -L "$absolute_path" ]]
  fi
}

# Resolve a PATH command once and hand callers the exact absolute spelling.
# Relative/empty PATH entries and shell functions are cwd- or process-local
# identities, so launchers must not defer them to a later exec.
shinsekai_normalize_absolute_link_target() {
  local raw="$1"
  local component
  local result=""
  local -a components
  local -a stack=()

  [[ -n "$raw" && "$raw" == /* && "$raw" != *\\* &&
     "$raw" != *$'\n'* && "$raw" != *$'\r'* &&
     "$raw" != *$'\t'* ]] || return 1
  IFS="/" read -r -a components <<< "$raw"
  for component in "${components[@]}"; do
    [[ -z "$component" || "$component" == "." ]] && continue
    if [[ "$component" == ".." ]]; then
      ((${#stack[@]} > 0)) || return 1
      stack=("${stack[@]:0:$((${#stack[@]} - 1))}")
      continue
    fi
    stack+=("$component")
  done
  ((${#stack[@]} > 0)) || return 1
  for component in "${stack[@]}"; do
    result="$result/$component"
  done
  shinsekai_absolute_path_is_exact "$result" || return 1
  printf '%s\n' "$result"
}

shinsekai_resolve_executable_candidate() {
  local candidate="$1"
  local link_target
  local parent
  local link_hops=0

  shinsekai_absolute_path_is_exact "$candidate" || return 1
  while [[ -L "$candidate" ]]; do
    ((link_hops += 1))
    ((link_hops <= 64)) || return 1
    parent="${candidate%/*}"
    [[ -n "$parent" ]] || parent="/"
    if [[ "$parent" != "/" ]]; then
      shinsekai_absolute_directory_is_real "$parent" || return 1
    fi
    link_target="$(/usr/bin/readlink "$candidate")" || return 1
    [[ -n "$link_target" ]] || return 1
    [[ "$link_target" == /* ]] || link_target="$parent/$link_target"
    candidate="$(shinsekai_normalize_absolute_link_target "$link_target")" ||
      return 1
  done
  shinsekai_absolute_file_is_real "$candidate" &&
    [[ -x "$candidate" ]] || return 1
  printf '%s\n' "$candidate"
}

shinsekai_resolve_executable() {
  local requested="$1"
  local candidate
  local directory
  local resolved
  local -a search_directories

  [[ -n "$requested" && "$requested" != *$'\n'* && "$requested" != *$'\r'* ]] ||
    return 1
  if [[ "$requested" == */* ]]; then
    shinsekai_resolve_executable_candidate "$requested"
    return
  else
    [[ "$requested" != "." && "$requested" != ".." &&
       "$requested" != *\\* ]] || return 1
    IFS=":" read -r -a search_directories <<< "${PATH-}"
    for directory in "${search_directories[@]}"; do
      shinsekai_absolute_path_is_exact "$directory" || continue
      candidate="$directory/$requested"
      if resolved="$(shinsekai_resolve_executable_candidate "$candidate")"; then
        printf '%s\n' "$resolved"
        return 0
      fi
    done
  fi
  return 1
}

shinsekai_resolve_conda_python() {
  local conda_executable="$1"
  local environment_name="$2"
  local probe_shell
  local output
  local line
  local prefix=""

  probe_shell="$(shinsekai_resolve_executable sh)" || return 1
  output="$(
    "$conda_executable" run --cwd / -n "$environment_name" "$probe_shell" -c \
      'printf "__SHINSEKAI_CONDA_PREFIX__=%s\n" "$CONDA_PREFIX"'
  )" || return 1
  while IFS= read -r line; do
    case "$line" in
      __SHINSEKAI_CONDA_PREFIX__=*)
        prefix="${line#__SHINSEKAI_CONDA_PREFIX__=}"
        ;;
    esac
  done <<< "$output"
  [[ -n "$prefix" && "$prefix" == /* && "$prefix" != *\\* ]] || return 1
  shinsekai_resolve_executable "$prefix/bin/python"
}

shinsekai_project_path_has_no_links() {
  local relative_path="$1"
  local cursor="$PROJECT_ROOT"
  local component
  local -a components

  [[ -n "$relative_path" && "$relative_path" != /* && "$relative_path" != *\\* ]] || return 1
  IFS="/" read -r -a components <<< "$relative_path"
  for component in "${components[@]}"; do
    [[ -n "$component" && "$component" != "." && "$component" != ".." ]] || return 1
    cursor="$cursor/$component"
    [[ ! -L "$cursor" ]] || return 1
  done
}

shinsekai_project_file_is_real() {
  local relative_path="$1"
  shinsekai_project_path_has_no_links "$relative_path" &&
    [[ -f "$PROJECT_ROOT/$relative_path" ]]
}

shinsekai_project_directory_is_real() {
  local relative_path="$1"
  shinsekai_project_path_has_no_links "$relative_path" &&
    [[ -d "$PROJECT_ROOT/$relative_path" ]]
}

shinsekai_project_directory_is_real_or_missing() {
  local relative_path="$1"
  local target="$PROJECT_ROOT/$relative_path"

  shinsekai_project_path_has_no_links "$relative_path" || return 1
  if [[ -e "$target" || -L "$target" ]]; then
    [[ -d "$target" && ! -L "$target" ]]
  fi
}

shinsekai_ensure_project_directory() {
  local relative_path="$1"
  local cursor="$PROJECT_ROOT"
  local component
  local -a components

  [[ -n "$relative_path" && "$relative_path" != /* && "$relative_path" != *\\* ]] || return 1
  IFS="/" read -r -a components <<< "$relative_path"
  for component in "${components[@]}"; do
    [[ -n "$component" && "$component" != "." && "$component" != ".." ]] || return 1
    cursor="$cursor/$component"
    [[ ! -L "$cursor" ]] || return 1
    if [[ ! -e "$cursor" ]]; then
      /bin/mkdir "$cursor" || return 1
    fi
    [[ -d "$cursor" && ! -L "$cursor" ]] || return 1
  done
}

shinsekai_find_embedded_python() {
  local relative_path
  for relative_path in \
    runtime/bin/python3.10 \
    runtime/bin/python3.11 \
    runtime/bin/python3.12 \
    runtime/bin/python3.13 \
    runtime/bin/python3 \
    runtime/bin/python \
    runtime/python.exe
  do
    if shinsekai_project_file_is_real "$relative_path" &&
      [[ -x "$PROJECT_ROOT/$relative_path" ]]; then
      printf '%s\n' "$PROJECT_ROOT/$relative_path"
      return 0
    fi
  done
  return 1
}

shinsekai_ensure_data_directories() {
  local relative_path
  for relative_path in \
    data/config \
    data/sprite \
    data/speech \
    data/models \
    data/chat_history \
    data/character_templates
  do
    shinsekai_ensure_project_directory "$relative_path" || {
      echo "Error: refusing unsafe project data directory: $PROJECT_ROOT/$relative_path" >&2
      return 1
    }
  done
}
