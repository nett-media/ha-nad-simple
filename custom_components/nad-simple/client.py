"""Async NAD Receiver Client - TCP and Serial support with push updates."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable

_LOGGER = logging.getLogger(__name__)


class NADClientError(Exception):
    """Base exception for NAD client errors."""


class NADClient(ABC):
    """Abstract NAD Receiver Client."""

    def __init__(self):
        """Initialize the NAD client."""
        self._connected = False
        self._callback: Callable[[str, str], None] | None = None
        self._reconnect_callback: Callable[[], None] | None = None
        self._listen_task: asyncio.Task | None = None
        self._buffer = ""
        self._reconnect_enabled = True
        self._is_reconnecting = False

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the NAD receiver."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the NAD receiver."""

    @abstractmethod
    async def _connect_impl(self) -> None:
        """Implementation-specific connect logic."""

    @abstractmethod
    async def send_raw(self, data: str) -> None:
        """Send raw data to the receiver."""

    async def _try_reconnect(self) -> bool:
        """Attempt to reconnect once.

        Returns:
            True if reconnect successful, False otherwise
        """
        if self._is_reconnecting:
            return False

        self._is_reconnecting = True

        try:
            _LOGGER.info("Attempting to reconnect to NAD receiver...")

            # Clean up old connection
            if self._listen_task and not self._listen_task.done():
                self._listen_task.cancel()
                try:
                    await self._listen_task
                except asyncio.CancelledError:
                    pass

            # Try to reconnect
            await self._connect_impl()
            self._connected = True
            _LOGGER.info("Successfully reconnected to NAD receiver")

            # Restart listen loop
            self._listen_task = asyncio.create_task(self._listen_loop())

            # Call reconnect callback if set
            if self._reconnect_callback:
                try:
                    self._reconnect_callback()
                except Exception as err:
                    _LOGGER.error("Error in reconnect callback: %s", err)

            self._is_reconnecting = False
            return True

        except Exception as err:
            _LOGGER.warning("Reconnect failed: %s", err)
            self._connected = False
            self._is_reconnecting = False
            return False

    def set_callback(self, callback: Callable[[str, str], None]) -> None:
        """Set callback for unsolicited messages.

        Args:
            callback: Function called with (key, value) when message received
            Example: callback("Main.Volume", "-50")
        """
        self._callback = callback

    def set_reconnect_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for reconnect events.

        Args:
            callback: Function called when reconnection is successful
        """
        self._reconnect_callback = callback

    def _parse_message(self, line: str) -> None:
        """Parse a message line and call callback.

        Format: "Key=Value"
        Example: "Main.Volume=-50"
        """
        line = line.strip()
        if not line:
            return

        # Parse message (format: "Key=Value")
        if "=" in line:
            key, value = line.split("=", 1)
            _LOGGER.debug("Received: %s = %s", key, value)

            # Call callback if set
            if self._callback:
                try:
                    self._callback(key, value)
                except Exception as err:
                    _LOGGER.error("Error in callback: %s", err)
        else:
            _LOGGER.debug("Received non-key-value message: %s", line)

    def _process_data(self, data: str) -> None:
        """Process incoming data and extract complete messages."""
        self._buffer += data

        # Process complete lines (terminated by \r, \n, or \r\n)
        while "\r" in self._buffer or "\n" in self._buffer:
            # Split on first line ending
            if "\r\n" in self._buffer:
                line, self._buffer = self._buffer.split("\r\n", 1)
            elif "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
            elif "\r" in self._buffer:
                line, self._buffer = self._buffer.split("\r", 1)
            else:
                break

            self._parse_message(line)

    async def send_command(
        self, command: str, operator: str = "?", value: str = ""
    ) -> None:
        """Send a command to the NAD receiver.

        Args:
            command: Command name (e.g., "Main.Power")
            operator: Operator ("?", "=", "+", "-")
            value: Value for "=" operator

        Example:
            await client.send_command("Main.Power", "?")  # Query
            await client.send_command("Main.Volume", "=", "-50")  # Set
            await client.send_command("Main.Volume", "+")  # Increment
        """
        # Build command string
        cmd = f"{command}{operator}"
        if value:
            cmd = f"{cmd}{value}"

        _LOGGER.debug("Sending command: %s", cmd)

        # Try to send, reconnect once if failed
        try:
            await self.send_raw(cmd)
        except NADClientError:
            if not self._connected and self._reconnect_enabled:
                _LOGGER.info("Command failed, attempting reconnect...")
                if await self._try_reconnect():
                    # Retry command after successful reconnect
                    _LOGGER.debug("Retrying command after reconnect: %s", cmd)
                    await self.send_raw(cmd)
                else:
                    raise
            else:
                raise

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connected


class NADTCPClient(NADClient):
    """NAD Receiver TCP/Telnet Client."""

    def __init__(self, host: str, port: int = 23):
        """Initialize TCP client.

        Args:
            host: IP address or hostname
            port: TCP port (default 23)
        """
        super().__init__()
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def _connect_impl(self) -> None:
        """Implementation-specific TCP connect logic."""
        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )
        _LOGGER.info("Connected to NAD receiver at %s:%s", self.host, self.port)

    async def connect(self) -> None:
        """Connect to the NAD receiver via TCP."""
        if self._connected:
            return

        try:
            await self._connect_impl()
            self._connected = True

            # Start listening for messages
            self._listen_task = asyncio.create_task(self._listen_loop())

        except (ConnectionRefusedError, OSError) as err:
            _LOGGER.error("Failed to connect to %s:%s: %s", self.host, self.port, err)
            raise NADClientError(f"Connection failed: {err}") from err

    async def disconnect(self) -> None:
        """Disconnect from the NAD receiver."""
        if not self._connected:
            return

        _LOGGER.debug("Disconnecting from NAD receiver")

        # Disable reconnect
        self._reconnect_enabled = False

        # Cancel listen task
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        # Close writer
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception as err:
                _LOGGER.debug("Error closing writer: %s", err)

        self._reader = None
        self._writer = None
        self._connected = False
        _LOGGER.info("Disconnected from NAD receiver")

    async def send_raw(self, data: str) -> None:
        """Send raw data to receiver (TCP: CR before and after)."""
        if not self._connected or not self._writer:
            raise NADClientError("Not connected")

        try:
            # NAD API: Send CR before and after command
            self._writer.write(f"\r{data}\r".encode("utf-8"))
            await self._writer.drain()
        except Exception as err:
            _LOGGER.error("Error sending data: %s", err)
            raise NADClientError(f"Failed to send data: {err}") from err

    async def _listen_loop(self) -> None:
        """Background task that listens for incoming messages."""
        _LOGGER.debug("Started listening for messages")

        try:
            while self._connected and self._reader:
                try:
                    # Read data from socket
                    data = await self._reader.read(4096)
                    if not data:
                        _LOGGER.warning("Connection closed by NAD receiver")
                        self._connected = False
                        break

                    # Decode and process
                    text = data.decode("utf-8", errors="ignore")
                    self._process_data(text)

                except asyncio.CancelledError:
                    break
                except Exception as err:
                    _LOGGER.error("Error in listen loop: %s", err)
                    self._connected = False
                    break

        except asyncio.CancelledError:
            pass
        finally:
            _LOGGER.debug("Stopped listening for messages")


class NADSerialClient(NADClient):
    """NAD Receiver Serial Client."""

    def __init__(self, port: str, baudrate: int = 115200):
        """Initialize serial client.

        Args:
            port: Serial port path (e.g., "/dev/ttyUSB0" or "COM3")
            baudrate: Baud rate (default 115200)
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def _connect_impl(self) -> None:
        """Implementation-specific serial connect logic."""
        import serial_asyncio

        _LOGGER.debug("Opening serial port %s at %d baud", self.port, self.baudrate)

        # Open serial port
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baudrate
        )
        _LOGGER.info(
            "Connected to NAD receiver on %s at %d baud", self.port, self.baudrate
        )

    async def connect(self) -> None:
        """Connect to the NAD receiver via Serial."""
        if self._connected:
            return

        try:
            await self._connect_impl()
            self._connected = True

            # Start listening for messages
            self._listen_task = asyncio.create_task(self._listen_loop())

        except Exception as err:
            _LOGGER.error(
                "Failed to open serial port %s: %s", self.port, err
            )
            raise NADClientError(f"Serial connection failed: {err}") from err

    async def disconnect(self) -> None:
        """Disconnect from the NAD receiver."""
        if not self._connected:
            return

        _LOGGER.debug("Disconnecting from NAD receiver")

        # Disable reconnect
        self._reconnect_enabled = False

        # Cancel listen task
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        # Close serial port
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception as err:
                _LOGGER.debug("Error closing serial port: %s", err)

        self._reader = None
        self._writer = None
        self._connected = False
        _LOGGER.info("Disconnected from NAD receiver")

    async def send_raw(self, data: str) -> None:
        """Send raw data to receiver (Serial: CR before and after)."""
        if not self._connected or not self._writer:
            raise NADClientError("Not connected")

        try:
            # NAD API: Send CR before and after command
            self._writer.write(f"\r{data}\r".encode("utf-8"))
            await self._writer.drain()
        except Exception as err:
            _LOGGER.error("Error sending data: %s", err)
            raise NADClientError(f"Failed to send data: {err}") from err

    async def _listen_loop(self) -> None:
        """Background task that listens for incoming messages."""
        _LOGGER.debug("Started listening for serial messages")

        try:
            while self._connected and self._reader:
                try:
                    # Read data from serial
                    data = await self._reader.read(4096)
                    if not data:
                        _LOGGER.warning("Serial connection closed")
                        self._connected = False
                        break

                    # Decode and process
                    text = data.decode("utf-8", errors="ignore")
                    self._process_data(text)

                except asyncio.CancelledError:
                    break
                except Exception as err:
                    _LOGGER.error("Error in serial listen loop: %s", err)
                    self._connected = False
                    break

        except asyncio.CancelledError:
            pass
        finally:
            _LOGGER.debug("Stopped listening for serial messages")
