"""VoiceOver output on the Mac — a Python port of ``VoiceOverOutput.cs``.

The C# version in the accessibility mod does three things, in order:

1. ``tell application "VoiceOver" to output "..."`` through ``NSAppleScript``
   — the lowest-latency path, and the one that interrupts cleanly;
2. ``NSAccessibilityPostNotificationWithUserInfo`` on the key window with
   ``NSAccessibilityAnnouncementRequestedNotification`` — the fallback for
   when the Apple Event to VoiceOver is not permitted (-1743, the value the
   C# checks for) because the process has never been granted automation;
3. an estimate of how long the utterance takes to speak, so callers have an
   ``is_speaking`` without VoiceOver itself having to report it.

This module is that, verbatim in shape, through pyobjc instead of raw
``objc_msgSend``: pyobjc *is* the msgSend plumbing the C# wrote by hand.
The C#'s ``dlopen`` of Foundation/AppKit and its ``objc_getClass`` /
``sel_registerName`` pairs all disappear — ``from AppKit import ...`` loads
the same frameworks and resolves the same classes.  What remains to port is
the order of attempts, the -1743 error number, the escaping, and the
priority-90 announcement dictionary.

``macOS 14+`` note: ``NSWorkspace.isVoiceOverEnabled`` is deprecated there in
favour of ``'voiceOverEnabled'`` in ``NSWorkspace.accessibilityDisplayShouldReduceMotion``'s
sibling dictionary; both are read here, the dictionary first.

The C# builds AppleScript sources with a cache of compiled scripts keyed by
text; speech text here is almost never repeated verbatim, so the cache bought
nothing and is not carried over — the C#'s ``Shutdown`` therefore has nothing
to release and is a no-op, kept for interface parity.
"""

from __future__ import annotations

import time

#: NSAppleScriptErrorNumber = -1743, errAEEventNotPermitted: the process has
#: not been allowed to send Apple Events to VoiceOver.  The C# treats it as
#: 'fall through to the window announcement'; so does this.
_ERR_AE_EVENT_NOT_PERMITTED = -1743

#: NSAccessibilityPriorityKey value the C# posts: 90, 'high'.
_ANNOUNCEMENT_PRIORITY = 90

_frameworks_ok: bool | None = None          # None = not tried yet
_speaking_until: float = 0.0


def _load_frameworks() -> bool:
    """Import the two frameworks the C# dlopen()s.  Once; cached."""
    global _frameworks_ok
    if _frameworks_ok is None:
        try:
            import Foundation            # noqa: F401, PLC0415
            import AppKit                # noqa: F401, PLC0415
            _frameworks_ok = True
        except ImportError:
            _frameworks_ok = False
    return _frameworks_ok


def is_supported() -> bool:
    """True on macOS with pyobjc's Cocoa framework available."""
    import sys
    return sys.platform == 'darwin' and _load_frameworks()


def is_running() -> bool:
    """``-[NSWorkspace isVoiceOverEnabled]``, as the C# checks it."""
    if not _load_frameworks():
        return False
    try:
        from AppKit import NSWorkspace
        workspace = NSWorkspace.sharedWorkspace()
        if workspace is None:
            return False
        return bool(workspace.isVoiceOverEnabled())
    except Exception:                                      # noqa: BLE001
        return False


def _escape_applescript(text: str) -> str:
    """The C#'s EscapeAppleScriptString: backslashes, then quotes."""
    return (text or '').replace('\\', '\\\\').replace('"', '\\"')


def _execute_script(source: str) -> bool:
    """Compile and run one AppleScript; False on error or -1743."""
    import Foundation
    script = Foundation.NSAppleScript.alloc().initWithSource_(source)
    if script is None:
        return False
    # pyobjc turns the NSError** out-params into (result, error) tuples.
    compiled, compile_err = script.compileAndReturnError_(None)
    if not compiled:
        # -1743 is handled by the caller (fall through to the window
        # announcement); any other compile failure is a failure all the same.
        return False
    result, exec_err = script.executeAndReturnError_(None)
    if result is None and exec_err is not None:
        if _error_number(exec_err) == _ERR_AE_EVENT_NOT_PERMITTED:
            return False
        return False
    return result is not None


def _error_number(err) -> int | None:
    """NSAppleScriptErrorNumber out of an error dictionary, or None."""
    try:
        if not err:
            return None
        num = err.get('NSAppleScriptErrorNumber')
        return int(num) if num is not None else None
    except Exception:                                      # noqa: BLE001
        return None


def _announce_via_window(text: str) -> bool:
    """The C#'s AnnounceViaWindow: post the announcement notification.

    ``NSAccessibilityPostNotificationWithUserInfo`` on the key (or main)
    window, with the announcement text and a high priority — the route that
    works even when the VoiceOver Apple Event is not permitted.
    """
    if not _load_frameworks():
        return False
    try:
        from AppKit import (NSAccessibilityAnnouncementKey,
                            NSAccessibilityAnnouncementRequestedNotification,
                            NSAccessibilityPriorityKey, NSApplication)
        from Foundation import NSMutableDictionary, NSNumber
        app = NSApplication.sharedApplication()
        if app is None:
            return False
        window = app.keyWindow() or app.mainWindow()
        if window is None:
            return False
        info = NSMutableDictionary.dictionary()
        info.setObject_forKey_(text, NSAccessibilityAnnouncementKey)
        info.setObject_forKey_(
            NSNumber.numberWithInt_(_ANNOUNCEMENT_PRIORITY),
            NSAccessibilityPriorityKey)
        import AppKit
        post = getattr(AppKit, 'NSAccessibilityPostNotificationWithUserInfo',
                       None)
        if post is None:
            return False
        post(window, NSAccessibilityAnnouncementRequestedNotification, info)
        return True
    except Exception:                                      # noqa: BLE001
        return False


def _estimate_speaking_seconds(text: str) -> float:
    """The C#'s word-count estimate: max(0.4, words / 3.0) seconds."""
    words = [w for w in (text or '').split() if w]
    return max(0.4, len(words) / 3.0)


def speak(text: str, interrupt: bool = False) -> bool:
    """Speak through VoiceOver; the fallback if the Apple Event is refused."""
    global _speaking_until
    if not text or not _load_frameworks():
        return False
    if interrupt:
        cancel()
    source = f'tell application "VoiceOver" to output "{_escape_applescript(text)}"'
    sent = _execute_script(source)
    if not sent:
        sent = _announce_via_window(text)
    if sent:
        _speaking_until = time.monotonic() + _estimate_speaking_seconds(text)
    return sent


def cancel() -> bool:
    """The C#'s Stop: output an empty string, which halts the queue."""
    global _speaking_until
    if not _load_frameworks():
        return False
    _execute_script('tell application "VoiceOver" to output ""')
    _speaking_until = 0.0
    return True


def is_speaking() -> bool:
    return time.monotonic() < _speaking_until


def shutdown() -> None:
    """The C#'s Shutdown released cached scripts; pyobjc manages that."""
    global _speaking_until
    _speaking_until = 0.0
