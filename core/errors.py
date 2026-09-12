class StageRetryable(Exception):
    """Transient failure. The worker loop retries with backoff."""


class StageFatal(Exception):
    """Bad input or unusable media. No retry."""
