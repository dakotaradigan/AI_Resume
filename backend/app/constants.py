"""User-facing messages and shared literals."""

SITE_URL = "https://www.dakotaradigan.io"

CHAT_LIMIT_MESSAGE = (
    "You've reached the free chat limit. To continue, enter the password "
    "found on Dakota's resume."
)

# 403 so the frontend shows the same password-unlock form as the free-chat wall:
# once unlocked, the visitor is unlimited and bypasses this per-IP cap.
IP_DAILY_LIMIT_MESSAGE = (
    "This network has reached today's free limit. To keep going, enter the "
    "password found on Dakota's resume."
)

BUSY_MESSAGE = (
    "Lots of interest today! The AI assistant is taking a quick break. "
    "Feel free to reach out directly at dakotaradigan@gmail.com or connect on LinkedIn. "
    "We'll be back soon!"
)

GENERIC_CHAT_ERROR = "Unable to process chat right now. Please try again soon."

JD_LIMIT_MESSAGE = (
    "You've used today's free fit analysis. Enter the password from Dakota's "
    "resume for unlimited access, or email dakotaradigan@gmail.com — he'd "
    "love to hear about the role."
)

PDF_LOCKED_MESSAGE = (
    "The PDF download is unlocked with the password found on Dakota's "
    "resume — the same one that unlocks unlimited chat."
)

# Neutral placeholder stored in history for a completed fit analysis (the raw
# JD is never persisted). Brief mode is gated by a server-owned metadata flag
# (SessionStore.mark_jd_analysis), not by scanning history for this string.
JD_SENTINEL = "[jd-analysis]"
