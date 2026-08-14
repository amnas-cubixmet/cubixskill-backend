# --------------------------------------------------------------
# Settings Resolution & Management Services
# Implements settings resolution order:
#   Academy override -> Platform default -> safe fallback.
# Resolves null Academy setting values by falling back to Platform defaults.
# Ensures setting changes affect future behavior without mutating past domain records.
# --------------------------------------------------------------
