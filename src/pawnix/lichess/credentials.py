"""Secure per-user storage for Lichess OAuth credentials."""

from __future__ import annotations

SERVICE_NAME = "Pawnix"
ACCOUNT_NAME = "lichess-oauth"


def load_token() -> str:
    """Read the saved OAuth token from the operating system credential store."""
    try:
        import keyring
    except ImportError:
        return ""
    try:
        return keyring.get_password(SERVICE_NAME, ACCOUNT_NAME) or ""
    except Exception:
        return ""


def save_token(token: str) -> None:
    """Store the OAuth token in the OS keychain; never fall back to plaintext."""
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Secure credential storage is unavailable. Reinstall Pawnix with its dependencies.") from exc
    try:
        keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, token)
        if keyring.get_password(SERVICE_NAME, ACCOUNT_NAME) != token:
            raise RuntimeError("The system credential store did not retain the Lichess token.")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not save the Lichess token to the system credential store: {exc}") from exc


def delete_token() -> None:
    """Remove a saved Lichess token from the OS credential store."""
    try:
        import keyring
    except ImportError:
        return
    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
    except keyring.errors.PasswordDeleteError:
        pass
