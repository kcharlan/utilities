#!/bin/zsh

set -eu
set -o pipefail
setopt NO_NOMATCH

PATH="/usr/bin:/bin:/usr/sbin:/sbin"

NAS_SERVER="192.168.1.18"
NAS_SHARE_NAME="kevin"
BACKUP_DIRECTORY_NAME="Moneydance-Mac-backups"
MAX_DAYS_TO_KEEP=4
DRY_RUN=0
LOG_FILE=""
USE_SYSLOG=0
SCRIPT_NAME="moneydance_rotate_backups"
DEBUG_LOG=0

MOUNT_BIN="/sbin/mount"
STAT_BIN="/usr/bin/stat"
FIND_BIN="/usr/bin/find"
DATE_BIN="/bin/date"
RM_BIN="/bin/rm"
LOGGER_BIN="/usr/bin/logger"
DIRNAME_BIN="/usr/bin/dirname"
MKDIR_BIN="/bin/mkdir"
AWK_BIN="/usr/bin/awk"
LS_BIN="/bin/ls"
ID_BIN="/usr/bin/id"
MKTEMP_BIN="/usr/bin/mktemp"

log_message() {
  local level="$1"
  shift
  local message="$*"
  local timestamp
  timestamp="$(${DATE_BIN} -u "+%Y-%m-%dT%H:%M:%SZ")"
  local formatted="${timestamp} ${SCRIPT_NAME}[$$] [${level}] ${message}"

  printf '%s\n' "${formatted}"

  if [[ -n "${LOG_FILE}" ]]; then
    local log_dir
    log_dir="$("${DIRNAME_BIN}" "${LOG_FILE}")"
    if [[ ! -d "${log_dir}" ]]; then
      "${MKDIR_BIN}" -p "${log_dir}"
    fi
    printf '%s\n' "${formatted}" >> "${LOG_FILE}"
  fi

  if [[ "${USE_SYSLOG}" -eq 1 && -x "${LOGGER_BIN}" ]]; then
    "${LOGGER_BIN}" -t "${SCRIPT_NAME}" "${message}"
  fi
}

log_debug() {
  if (( DEBUG_LOG )); then
    log_message "DEBUG" "$@"
  fi
}

exit_with_error() {
  log_message "ERROR" "$*"
  exit 1
}

if ! command -v "${MOUNT_BIN}" >/dev/null 2>&1; then
  exit_with_error "Mount binary not found at ${MOUNT_BIN}"
fi

mount_line=""
while IFS= read -r line; do
  if [[ "${line}" == *"${NAS_SERVER}/${NAS_SHARE_NAME}"* ]]; then
    mount_line="${line}"
    break
  fi
done < <("${MOUNT_BIN}")

if [[ -z "${mount_line}" ]]; then
  log_message "WARN" "Share ${NAS_SERVER}/${NAS_SHARE_NAME} is not mounted; skipping cleanup."
  exit 0
fi

log_debug "Matched mount line: ${mount_line}"

mount_point="$("${AWK_BIN}" '{
  for (i = 1; i <= NF; i++) {
    if ($i == "on" && (i + 1) <= NF) {
      print $(i + 1)
      exit
    }
  }
}' <<< "${mount_line}")"

if [[ -z "${mount_point}" || ! -d "${mount_point}" ]]; then
  log_message "WARN" "Mount point derived from mount table is invalid (${mount_point}); skipping cleanup."
  exit 0
fi

log_debug "Derived mount point: ${mount_point}"

backup_dir="${mount_point%/}/${BACKUP_DIRECTORY_NAME}"

if [[ ! -d "${backup_dir}" ]]; then
  log_message "WARN" "Backup directory not found at ${backup_dir}; skipping cleanup."
  exit 0
fi

if [[ ! -r "${backup_dir}" || ! -x "${backup_dir}" ]]; then
  log_message "WARN" "Backup directory at ${backup_dir} is not accessible (check mount or permissions); skipping cleanup."
  exit 0
fi

if [[ -x "${LS_BIN}" ]]; then
  dir_listing="$("${LS_BIN}" -ld "${backup_dir}" 2>&1 || true)"
  log_debug "Backup directory metadata: ${dir_listing}"
fi

if ! command -v "${FIND_BIN}" >/dev/null 2>&1; then
  exit_with_error "Find binary not found at ${FIND_BIN}"
fi
if ! command -v "${STAT_BIN}" >/dev/null 2>&1; then
  exit_with_error "Stat binary not found at ${STAT_BIN}"
fi
if ! command -v "${DATE_BIN}" >/dev/null 2>&1; then
  exit_with_error "Date binary not found at ${DATE_BIN}"
fi
if ! command -v "${RM_BIN}" >/dev/null 2>&1 && [[ "${DRY_RUN}" -eq 0 ]]; then
  exit_with_error "rm binary not found at ${RM_BIN}"
fi
if [[ -n "${LOG_FILE}" ]]; then
  if ! command -v "${DIRNAME_BIN}" >/dev/null 2>&1; then
    exit_with_error "dirname binary not found at ${DIRNAME_BIN}"
  fi
  if ! command -v "${MKDIR_BIN}" >/dev/null 2>&1; then
    exit_with_error "mkdir binary not found at ${MKDIR_BIN}"
  fi
fi
if ! command -v "${AWK_BIN}" >/dev/null 2>&1; then
  exit_with_error "awk binary not found at ${AWK_BIN}"
fi
if ! command -v "${MKTEMP_BIN}" >/dev/null 2>&1; then
  exit_with_error "mktemp binary not found at ${MKTEMP_BIN}"
fi

if [[ -x "${ID_BIN}" ]]; then
  current_user="$("${ID_BIN}" -un 2>/dev/null || true)"
  current_uid="$("${ID_BIN}" -u 2>/dev/null || true)"
  log_debug "Running as user=${current_user} (uid=${current_uid}) HOME=${HOME:-}"
fi

log_message "INFO" "Inspecting backups in ${backup_dir}"

typeset -a backup_files=()
typeset -a backup_file_days=()

find_output_tmp="$("${MKTEMP_BIN}" -t "${SCRIPT_NAME}.find.XXXXXX")"
find_error_tmp="$("${MKTEMP_BIN}" -t "${SCRIPT_NAME}.find.err.XXXXXX")"

if "${FIND_BIN}" "${backup_dir}" -type f -print0 > "${find_output_tmp}" 2> "${find_error_tmp}"; then
  while IFS= read -r -d '' file_path; do
    if [[ ! -f "${file_path}" ]]; then
      continue
    fi

    mtime_epoch="$(${STAT_BIN} -f "%m" "${file_path}")" || continue
    file_day="$(${DATE_BIN} -r "${mtime_epoch}" "+%Y-%m-%d")" || continue

    backup_files+=("${file_path}")
    backup_file_days+=("${file_day}")
  done < "${find_output_tmp}"

  rm -f "${find_output_tmp}" "${find_error_tmp}"
else
  find_errors="$(
    if [[ -f "${find_error_tmp}" ]]; then
      <"${find_error_tmp}"
    fi
  )"

  if [[ -n "${find_errors}" ]]; then
    while IFS= read -r err_line; do
      [[ -n "${err_line}" ]] && log_message "ERROR" "find stderr: ${err_line}"
    done <<< "${find_errors}"
  fi

  rm -f "${find_output_tmp}" "${find_error_tmp}"

  if [[ "${find_errors}" == *"Operation not permitted"* ]]; then
    log_message "ERROR" "Filesystem scan was denied (Operation not permitted). Grant Full Disk Access to the shell executing this script or adjust launchd to use a shell binary that already has that entitlement."
    exit 1
  else
    exit_with_error "Failed to enumerate backup files under ${backup_dir}"
  fi
fi

typeset -a unique_days=("${(@u)backup_file_days}")
log_debug "Unique days (unsorted): ${unique_days[*]}"

if (( ${#unique_days[@]} == 0 )); then
  log_message "INFO" "No backup files found under ${backup_dir}"
  exit 0
fi

typeset -a sorted_days=("${(@o)unique_days}")
log_debug "Unique days (sorted ascending): ${sorted_days[*]}"

integer day_count=${#sorted_days[@]}
log_debug "Unique day count: ${day_count}"
if (( day_count <= MAX_DAYS_TO_KEEP )); then
  log_message "INFO" "Found ${day_count} day(s) of backups; retention is ${MAX_DAYS_TO_KEEP}. Nothing to purge."
  exit 0
fi

typeset -A keep_days=()
typeset -a days_desc=("${(@O)sorted_days}")
log_debug "Days sorted descending: ${days_desc[*]}"

for day in "${days_desc[@]}"; do
  if (( ${#keep_days[@]} < MAX_DAYS_TO_KEEP )); then
    keep_days[$day]=1
  else
    break
  fi
done

typeset -a purge_candidates=()
log_debug "Retention day keys (pending): ${(k)keep_days}"

integer idx=1
while (( idx <= ${#backup_files[@]} )); do
  file="${backup_files[idx]}"
  day="${backup_file_days[idx]}"
  if (( ${+keep_days[$day]} )); then
    log_debug "Retaining file within retention: ${file}"
  else
    purge_candidates+=("${file}")
  fi
  (( idx += 1 ))
done

log_debug "Retention day keys: ${(k)keep_days}"
log_debug "Purge candidate count: ${#purge_candidates[@]}"

if (( ${#purge_candidates[@]} == 0 )); then
  log_message "INFO" "No files identified for purging after retention check."
  exit 0
fi

log_message "INFO" "Preparing to purge ${#purge_candidates[@]} file(s) older than the newest ${MAX_DAYS_TO_KEEP} day(s)."

integer removed=0
for file in "${purge_candidates[@]}"; do
  log_message "INFO" "Removing ${file}"
  if (( DRY_RUN )); then
    continue
  fi
  if "${RM_BIN}" -f "${file}"; then
    (( removed += 1 ))
  else
    log_message "ERROR" "Failed to remove ${file}"
  fi
done

if (( DRY_RUN )); then
  log_message "INFO" "Dry run enabled; no files were deleted."
else
  log_message "INFO" "Removed ${removed} file(s)."
fi
