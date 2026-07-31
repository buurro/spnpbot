import time

# Anchor for startup-phase logging: the app package is the first thing the
# server imports, so this runs before any heavy imports (aiogram, etc.).
STARTUP_T0 = time.monotonic()
