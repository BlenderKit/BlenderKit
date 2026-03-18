"""Blenderkit Specific Exceptions."""


class BlenderkitError(Exception):
    """Base exception for Blenderkit Addon."""


class DownloadError(BlenderkitError):
    """Exception raised when a download fails."""


class AppendError(BlenderkitError):
    """Exception raised when an append or link of the asset fails."""



class ActivationError(BlenderkitError):
    """Raised when an object cannot be activated."""


class MissingObjectError(BlenderkitError):
    """Raised when an expected object is missing."""


class InstallationError(BlenderkitError):
    """Raised when an asset cannot be installed."""


class DeactivationError(BlenderkitError):
    """Raised when an object cannot be deactivated."""
    

class UninstallationError(BlenderkitError):
    """Raised when an asset cannot be uninstalled."""
