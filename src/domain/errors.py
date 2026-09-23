"""Error taxonomy (POD-405, POD-507). Messages must never contain source values or SQL text."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    VALIDATION = "VALIDATION"
    DATA_CONTRACT = "DATA_CONTRACT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


RETRYABLE: frozenset[ErrorCode] = frozenset(
    {ErrorCode.SOURCE_UNAVAILABLE, ErrorCode.TIMEOUT, ErrorCode.DEPENDENCY_FAILED}
)


class DomainError(Exception):
    code: ErrorCode = ErrorCode.INTERNAL

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            **self.details,
        }


class NotFound(DomainError):
    code = ErrorCode.NOT_FOUND


class Forbidden(DomainError):
    code = ErrorCode.FORBIDDEN


class ApprovalRequired(DomainError):
    code = ErrorCode.APPROVAL_REQUIRED


class PolicyViolation(DomainError):
    code = ErrorCode.POLICY_VIOLATION


class ValidationFailed(DomainError):
    code = ErrorCode.VALIDATION


class DataContractError(DomainError):
    code = ErrorCode.DATA_CONTRACT


class SourceUnavailable(DomainError):
    code = ErrorCode.SOURCE_UNAVAILABLE


class SourceTimeout(DomainError):
    code = ErrorCode.TIMEOUT


class DependencyFailed(DomainError):
    code = ErrorCode.DEPENDENCY_FAILED


class Conflict(DomainError):
    code = ErrorCode.CONFLICT


class NotImplementedStep(DomainError):
    code = ErrorCode.INTERNAL
