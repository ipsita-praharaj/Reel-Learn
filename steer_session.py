"""
steer_session.py — pause a live HAI desktop session, inject a human steering
message, then resume it. For use while a session started by fix_noisy_poem.py
(or anything similar) is still running and you're watching your own screen
and want to redirect it — "stop, look here instead" — without waiting for it
to time out or fail on its own first.

These are server-side session controls, independent of whichever local
process is holding the desktop bridge open for that session, so this can be
run from a separate terminal/process while the original script is still mid-run.

Usage:
  python steer_session.py <session_id> "<message>"

Example:
  python steer_session.py 4c39d50c-1d10-4f8f-9d2f-51f6895d390f \\
      "Stop. There are two overlapping Audacity windows visible right now. \\
       Close the one behind, then reselect the noise region in the remaining one."
"""

import sys

from hai_agents import Client
from hai_agents.sessions.types.send_session_messages_request_body import (
    SendSessionMessagesRequestBody_UserMessage,
)

client = Client()


def main() -> None:
    session_id, message = sys.argv[1], sys.argv[2]

    client.sessions.pause_session(session_id)
    print(f"Paused {session_id}")

    client.sessions.send_session_messages(
        session_id,
        request=SendSessionMessagesRequestBody_UserMessage(message=message),
    )
    print(f"Sent steering message: {message}")

    client.sessions.resume_session(session_id)
    print(f"Resumed {session_id}")


if __name__ == "__main__":
    main()
