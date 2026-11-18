#!/usr/bin/env bash
# OLD and NEW must stamp the checked-out source, not the CI driver's ref.
# A subshell preserves the workflow's identity and the git URL redirect.
source_build_env() (
  unset GITHUB_SHA GITHUB_REF GITHUB_REF_NAME GITHUB_HEAD_REF GITHUB_BASE_REF
  unset SLAVE_BUILD_COMMIT SLAVE_PAYLOAD_TAG SLAVE_PAYLOAD_VERSION SLAVE_DESKTOP_VARIANT
  "$@"
)