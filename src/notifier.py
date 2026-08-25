def notify(title: str, message: str, enabled: bool=True) -> bool:
    """Send a desktop notification and report whether it was actually delivered.

    Notification failures must never break the job-search pipeline.
    """
    if not enabled:
        return False
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
        return True
    except Exception:
        return False
