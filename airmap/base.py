"""Common scanner interface and error handling shared by all platforms."""

from __future__ import annotations

import abc
import logging
import shutil
import subprocess
from collections.abc import Sequence
from typing import ClassVar

from .models import NetworkInfo

logger = logging.getLogger(__name__)


class WifiScannerError(Exception):
    """Base class for all airmap scanner errors."""


class ScanParseError(WifiScannerError):
    """Raised only when scan output is structurally unrecognizable.

    This is deliberately the *sole* exception `scan()` may raise. Every other
    failure mode (missing tool, timeout, permission error, non-zero exit,
    genuinely zero networks in range) resolves to an empty list plus a
    warning log, because those are all expected/transient conditions that a
    caller should be able to treat uniformly as "no results right now".
    A `ScanParseError` means the output format itself no longer matches what
    the parser expects (e.g. a tool version upgrade changed its output shape)
    -- silently returning `[]` for that would be indistinguishable from the
    common, benign "no networks nearby" case and could hide a real bug.
    """


class UnsupportedPlatformError(RuntimeError):
    """Raised by the factory for an OS with no scanner implementation.

    Subclasses RuntimeError rather than NotImplementedError: the latter is
    conventionally reserved for "this abstract method body isn't implemented
    yet", not "your OS isn't supported". A dedicated type also lets callers
    catch this specific case without swallowing unrelated NotImplementedErrors.
    """


class WifiScanner(abc.ABC):
    """Common interface for OS-specific WiFi scanners."""

    TOOL_NAME: ClassVar[str]

    def is_available(self) -> bool:
        """Check whether the required system tool is present on PATH."""
        return shutil.which(self.TOOL_NAME) is not None

    @abc.abstractmethod
    def scan(self) -> list[NetworkInfo]:
        """Perform a scan and return the list of currently visible networks.

        Must never raise except `ScanParseError` -- see that class's
        docstring for the rationale.
        """
        raise NotImplementedError

    def _run_command(
        self,
        args: Sequence[str],
        *,
        timeout: float = 10.0,
        encoding: str = "utf-8",
    ) -> str | None:
        """Run a system command and return decoded stdout, or None on failure.

        Centralizes the subprocess invocation and error classification that
        is identical between platforms (missing binary, timeout, permission
        errors, non-zero exit) so each scanner only needs to handle the parts
        that actually differ: the command itself, its output encoding, and
        how to parse the resulting text.
        """
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            logger.error("%s not found on PATH", args[0])
            return None
        except subprocess.TimeoutExpired:
            logger.error("%s timed out after %.1fs", args[0], timeout)
            return None
        except OSError as exc:
            logger.error("failed to launch %s: %s", args[0], exc)
            return None

        if proc.returncode != 0:
            stderr_excerpt = proc.stderr.decode(encoding, errors="replace").strip()[:500]
            logger.warning(
                "%s exited with code %d: %s", args[0], proc.returncode, stderr_excerpt
            )
            return None

        return proc.stdout.decode(encoding, errors="replace")
