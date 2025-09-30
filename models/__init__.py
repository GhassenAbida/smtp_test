"""
Data models for SMTP email sending functionality.
"""

from typing import List, Optional


class SMTPCredentials:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        encryption: str,
        from_address: str,
        from_name: str,
        group_name: str = "standalone_test",
        provider_key: str = "zepto_mail",
        source_file: str = "standalone_smtp_test.py",
        is_valid: bool = True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.encryption = encryption
        self.from_address = from_address
        self.from_name = from_name
        self.group_name = group_name
        self.provider_key = provider_key
        self.source_file = source_file
        self.is_valid = is_valid


class AttemptResult:
    def __init__(self, mode: str, success: bool, duration_ms: int, error_message: Optional[str] = None):
        self.mode = mode
        self.success = success
        self.duration_ms = duration_ms
        self.error_message = error_message


class SMTPTestResult:
    def __init__(
        self,
        success: bool,
        message: str,
        duration_ms: int,
        mode_used: str,
        attempts: List[AttemptResult],
        error_message: Optional[str] = None,
    ):
        self.success = success
        self.message = message
        self.duration_ms = duration_ms
        self.mode_used = mode_used
        self.attempts = attempts
        self.error_message = error_message