"""PayPal error types."""

from __future__ import annotations


class PayPalError(RuntimeError):
    """A PayPal API call failed.

    Carries PayPal's ``debug_id`` so a failure can be quoted to PayPal support or
    searched in the sandbox dashboard.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        name: str = "",
        debug_id: str = "",
        issues: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.name = name
        self.debug_id = debug_id
        self.issues = issues or []
        self.message = message
        super().__init__(self._format())

    def _format(self) -> str:
        head = f"PayPal API error {self.status_code} {self.name}".strip()
        text = f"{head}: {self.message}" if self.message else head
        extras = []
        if self.issues:
            extras.append(f"issues={self.issues}")
        if self.debug_id:
            extras.append(f"debug_id={self.debug_id}")
        return f"{text} ({', '.join(extras)})" if extras else text
