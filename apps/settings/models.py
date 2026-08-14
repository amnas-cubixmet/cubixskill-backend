# --------------------------------------------------------------
# Platform & Academy Settings Models
# PlatformSettings defines platform-wide defaults.
# AcademySettings stores Academy-specific overrides.
# Settings resolution order is:
#   Academy override -> Platform default -> safe fallback.
# Null Academy values mean "inherit Platform default" where supported.
# Settings must use typed fields, not a generic key/value dumping ground.
# Setting changes normally affect future behavior and should not silently rewrite existing domain records.
# Academy settings must enforce tenant isolation.
# Sensitive configuration and credentials must not be exposed through public APIs or logs.
# --------------------------------------------------------------
