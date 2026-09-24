import inspect
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from logging.handlers import BaseRotatingHandler

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# -------------------------------------------------------------------
# Correlation ID Management
# -------------------------------------------------------------------
# ContextVar holds the request-scoped correlation ID across async calls
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation ID into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        cid = correlation_id_ctx.get()
        if cid:
            record.correlation_id = f" [ID: {cid}]"
        else:
            record.correlation_id = ""
        return True


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Extracts or generates X-Correlation-ID for each request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Pick correlation ID from incoming header or generate a new one
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_ctx.set(correlation_id)

        try:
            response = await call_next(request)
            # Send correlation ID back in response headers for traceability
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            correlation_id_ctx.reset(token)


# -------------------------------------------------------------------
# Custom Handler: Rotate on Date (Midnight) OR File Size
# -------------------------------------------------------------------
class SizeAndTimeRotatingFileHandler(BaseRotatingHandler):
    """
    Rotates log files when:
    1. The file size exceeds max_bytes, OR
    2. Midnight is crossed (new day).

    Active file:   <name>.log (e.g., advisory-service.log)
    Rolled files:  <name>-YYYY-MM-DD-HH-MM-SS.log
    """

    def __init__(
        self, filename: str, max_bytes: int = 10 * 1024 * 1024, encoding: str = "utf-8"
    ):
        # Extract the folder path from the filename
        log_dir = os.path.dirname(filename)
        # If a folder was specified (e.g., 'logs/'), create it if it doesn't exist
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        super().__init__(filename, mode="a", encoding=encoding, delay=False)
        self.max_bytes = max_bytes
        self.rollover_at = self._compute_next_midnight()

    def _compute_next_midnight(self) -> int:
        now = time.localtime()
        # Compute seconds remaining until 00:00:00 tomorrow
        seconds_until_midnight = (
            (24 - now.tm_hour - 1) * 3600
            + (60 - now.tm_min - 1) * 60
            + (60 - now.tm_sec)
        ) + 1
        return int(time.time()) + seconds_until_midnight

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if self.stream is None:
            self.stream = self._open()

        # 1. Size check
        if self.max_bytes > 0:
            msg = "%s\n" % self.format(record)
            self.stream.seek(0, 2)  # Seek to end of file
            if (
                self.stream.tell() + len(msg.encode(self.encoding or "utf-8"))
                >= self.max_bytes
            ):
                return 1

        # 2. Midnight / Date check
        if int(time.time()) >= self.rollover_at:
            return 1

        return 0

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None

        # Build rolled file name: advisory-service-YYYY-MM-DD-HH-MM-SS.log
        dir_name, base_name = os.path.split(self.baseFilename)
        name, ext = os.path.splitext(base_name)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        target_name = os.path.join(dir_name, f"{name}-{timestamp}{ext}")

        # Guard against collisions if multiple rotations occur in the same second
        counter = 1
        final_target = target_name
        while os.path.exists(final_target):
            final_target = os.path.join(dir_name, f"{name}-{timestamp}_{counter}{ext}")
            counter += 1

        if os.path.exists(self.baseFilename):
            os.rename(self.baseFilename, final_target)

        # Reset next rollover target to the next midnight
        self.rollover_at = self._compute_next_midnight()

        if not self.delay:
            self.stream = self._open()


# -------------------------------------------------------------------
# Setup Logger
# -------------------------------------------------------------------
def setup_global_logging():
    # Target the root logger by passing no name
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if called multiple times
    if root_logger.handlers:
        return

    log_format = logging.Formatter(
        "%(asctime)s [%(levelname)s]%(correlation_id)s [%(name)s]: %(message)s"
    )
    corr_filter = CorrelationIdFilter()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.addFilter(corr_filter)

    # File Handler
    file_handler = SizeAndTimeRotatingFileHandler(
        filename="logs/advisory-service.log",
        max_bytes=10 * 1024 * 1024,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)
    file_handler.addFilter(corr_filter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def set_correlation_id(prefix: str | None = None, suffix: str | None = None) -> str:
    """Dynamically updates the correlation ID inside any running method."""
    parts = []

    if prefix:
        parts.append(str(prefix))

    parts.append(uuid.uuid4().hex)

    if suffix:
        parts.append(str(suffix))

    new_id = "-".join(parts)
    correlation_id_ctx.set(new_id)
    return new_id


def with_correlation_id(
    prefix: str | None = None,
    suffix: str | None = None,
    prefix_arg: str = "prefix",
    suffix_arg: str = "suffix",
):
    """
    Applies a correlation ID to the function.
    - Uses prefix/suffix ONLY if a non-empty value is found in the function call
      or the decorator parameters.
    - If neither is provided, falls back to ONLY the UUID.
    """

    def decorator(func):
        sig = inspect.signature(func)

        def _resolve_part(
            arg_name: str, static_val: str | None, bound_args
        ) -> str | None:
            # Check if the wrapped function received this argument with a valid value
            if arg_name in bound_args.arguments:
                val = bound_args.arguments[arg_name]
                if val is not None and str(val).strip():
                    return str(val).strip()

            # Check if a static value was passed to the decorator
            if static_val is not None and str(static_val).strip():
                return str(static_val).strip()

            # No value provided
            return None

        def _build_correlation_id(args, kwargs) -> str:
            bound_args = sig.bind_partial(*args, **kwargs)
            bound_args.apply_defaults()

            resolved_prefix = _resolve_part(prefix_arg, prefix, bound_args)
            resolved_suffix = _resolve_part(suffix_arg, suffix, bound_args)

            # Build the ID with only the available parts
            parts = []
            if resolved_prefix:
                parts.append(resolved_prefix)

            parts.append(uuid.uuid4().hex)

            if resolved_suffix:
                parts.append(resolved_suffix)

            return "-".join(parts)

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                corr_id = _build_correlation_id(args, kwargs)
                token = correlation_id_ctx.set(corr_id)
                try:
                    return await func(*args, **kwargs)
                finally:
                    correlation_id_ctx.reset(token)

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                corr_id = _build_correlation_id(args, kwargs)
                token = correlation_id_ctx.set(corr_id)
                try:
                    return func(*args, **kwargs)
                finally:
                    correlation_id_ctx.reset(token)

            return sync_wrapper

    return decorator


def with_correlation_subid(
    suffix: str | None = None,
    suffix_arg: str = "suffix",
):
    """
    Appends a sub-identifier (suffix) to the CURRENTLY ACTIVE correlation ID.
    - If parent ID is 'batch-1234', and suffix is 'auth', sub-id becomes: 'batch-1234-auth'
    - When the decorated function finishes, it automatically reverts to 'batch-1234'.
    - If no parent ID exists (or is '-'), it generates a UUID and appends the suffix.
    """

    def decorator(func):
        real_func = inspect.unwrap(func)
        sig = inspect.signature(real_func)
        param_names = list(sig.parameters.keys())

        def _extract_suffix(args, kwargs) -> str | None:
            # Check keyword arguments
            if suffix_arg in kwargs and kwargs[suffix_arg] is not None:
                val = str(kwargs[suffix_arg]).strip()
                if val:
                    return val

            # Check positional arguments
            if suffix_arg in param_names:
                idx = param_names.index(suffix_arg)
                if idx < len(args) and args[idx] is not None:
                    val = str(args[idx]).strip()
                    if val:
                        return val

            # Fall back to static suffix passed to the decorator
            if suffix is not None and str(suffix).strip():
                return str(suffix).strip()

            return None

        def _compute_sub_correlation_id(args, kwargs) -> str:
            resolved_suffix = _extract_suffix(args, kwargs)
            parent_id = correlation_id_ctx.get()

            # If parent ID doesn't exist or is default "-", fallback to a fresh UUID
            base_id = (
                parent_id if (parent_id and parent_id != "-") else uuid.uuid4().hex
            )

            if resolved_suffix:
                return f"{base_id}-{resolved_suffix}"
            return base_id

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                sub_id = _compute_sub_correlation_id(args, kwargs)
                token = correlation_id_ctx.set(sub_id)
                try:
                    return await func(*args, **kwargs)
                finally:
                    correlation_id_ctx.reset(token)

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                sub_id = _compute_sub_correlation_id(args, kwargs)
                token = correlation_id_ctx.set(sub_id)
                try:
                    return func(*args, **kwargs)
                finally:
                    correlation_id_ctx.reset(token)

            return sync_wrapper

    return decorator
