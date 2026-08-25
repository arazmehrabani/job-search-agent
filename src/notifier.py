
def notify(title: str, message: str, enabled: bool=True):
    print(f"\n[{title}] {message}\n")
    if not enabled:
        return
    try:
        from plyer import notification
        notification.notify(title=title,message=message,timeout=10)
    except Exception:
        pass
