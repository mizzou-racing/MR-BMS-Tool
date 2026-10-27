import can, time, threading
import serial, serial.serialutil

# CANdapter serial protocol (Ewert Energy manual):
#   Tiiildd..[CR]        transmit STANDARD (11-bit) frame, 3 hex digit ID
#   Xiiiiiiiildd..[CR]   transmit EXTENDED (29-bit) frame, 8 hex digit ID
#   every command is answered with ACK (0x06) = OK or BELL (0x07) = error
# Received frames come back as t/T + 3 digit ID (standard) or x/X + 8 digit ID (extended).
#
# The CANdapter must be polled continuously, otherwise its FIFO fills up and it
# stops transmitting, so the reader should keep running while you send.

ACK = 0x06
NAK = 0x07

STD_MAX_ID = 0x7FF
EXT_MAX_ID = 0x1FFFFFFF

READ_TIMEOUT = 0.05      # seconds. Keeps any single serial read short so the lock is released often
ACK_TIMEOUT  = 0.5       # seconds to wait for ACK/NAK after sending a command
MAX_RX_BYTES = 8192      # safety cap on the receive buffer


class pyCandapter:
    def __init__(self, port, baudrate = 9600) -> None:

        # One lock for the serial port so the worker thread and the sender never interleave
        self.lock = threading.RLock()

        # Bytes received but not yet consumed (frames are split on '\r')
        self._rx = bytearray()

        # Number of senders waiting for the lock. The reader steps aside while this is > 0
        # so a send is never starved by a worker that re-grabs the lock in a tight loop.
        self._tx_waiting = 0
        self._tx_waiting_lock = threading.Lock()

        try:
            self.device = serial.Serial(port=port, baudrate=baudrate, timeout=READ_TIMEOUT)
            print(f"[INFO] Connected to {port} at {baudrate} baud.")
        except serial.serialutil.SerialException as e:
            print(f"[ERROR] Could not open port {port}: {e}")
            self.device = None 

    # ------------------------------------------------------------------
    # low level helpers (call with self.lock held)
    # ------------------------------------------------------------------
    def _fill(self):
        """Pull whatever is waiting on the port into the buffer (blocks at most READ_TIMEOUT)."""
        data = self.device.read(self.device.in_waiting or 1)
        if data:
            self._rx += data
            if len(self._rx) > MAX_RX_BYTES:          # nobody is reading, drop the oldest bytes
                del self._rx[:len(self._rx) - MAX_RX_BYTES // 4]

    def _take_ack(self):
        """Remove the first ACK/NAK byte from the buffer and return it, or None."""
        for i, b in enumerate(self._rx):
            if b in (ACK, NAK):
                del self._rx[i]
                return b
        return None

    # ------------------------------------------------------------------

    def openCANBus(self, baudrate) -> bool:
        baudrateCodes = {10000: 0, 20000: 1, 50000: 2, 100000: 3, 125000: 4, 250000: 5, 500000: 6, 800000: 7, 1000000: 8}

        if self.device is None:
            raise RuntimeError("[ERROR] Serial port is not open. Cannot open CAN bus.")

        #-------------------------
        self.sendSerialMessage('C')
        #-------------------------
        
        try:
            code = baudrateCodes[baudrate]
        except KeyError:
            raise ValueError('Invalid baudrate')
        
        status = self.sendSerialMessage('S{}'.format(code))

        if status == True:
            status = self.sendSerialMessage('O')
            if status == True:
                return True
            else:
                raise ValueError('Error opening CAN bus')
        else:
            raise ValueError('Error setting baudrate')

    def sendSerialMessage(self, message, timeout=ACK_TIMEOUT) -> bool:
        with self._tx_waiting_lock:
            self._tx_waiting += 1
        try:
            with self.lock:
                # Pick up anything already waiting, then discard stale ACK/NAK bytes from earlier commands
                if self.device.in_waiting:
                    self._rx += self.device.read(self.device.in_waiting)
                self._rx[:] = bytes(b for b in self._rx if b not in (ACK, NAK))

                self.device.write('{}\r'.format(message).encode())

                # Streamed frames may arrive before the ACK. Leave them in the buffer for the
                # reader and only pick out the ACK/NAK byte.
                response = None
                deadline = time.time() + timeout
                while True:
                    response = self._take_ack()
                    if response is not None or time.time() >= deadline:
                        break
                    self._fill()
        finally:
            with self._tx_waiting_lock:
                self._tx_waiting -= 1

        print(f"Sent: {message!r} | Got: {'ACK' if response == ACK else 'NAK' if response == NAK else 'no reply'}")

        return response == ACK

    def readCANMessage(self,filterID=None) -> can.Message:
        # Let a pending send go first
        if self._tx_waiting:
            time.sleep(0.005)
            return None

        with self.lock:
            end = self._rx.find(b'\r')
            if end < 0:
                self._fill()
                end = self._rx.find(b'\r')
            if end < 0:
                return None                 # no complete frame yet (nothing is wrong)

            raw = bytes(self._rx[:end])
            del self._rx[:end + 1]

        return self._parseFrame(raw, filterID)

    def _parseFrame(self, raw, filterID=None):
        # An ACK/NAK byte can end up glued to the front of a frame, so strip them
        message = raw.decode('ascii', errors='ignore').strip('\x06\x07\r\n ')

        if not message:
            return None

        frame_type = message[0].lower()

        if frame_type == 'x':           # Extended data frame (29-bit ID), 8 hex digits
            is_extended = True
            id_len = 8
        elif frame_type == 't':         # Standard data frame (11-bit ID), 3 hex digits
            is_extended = False
            id_len = 3
        else:
            return None                 # RTR, version string, or garbage

        try:
            messageID     = int(message[1 : 1 + id_len], 16)
            messageLength = int(message[1 + id_len])           # DLC (0-8)

            data_start = 1 + id_len + 1
            if messageLength > 8 or len(message) < data_start + 2 * messageLength:
                return None             # truncated frame

            messageDataArr = [
                int(message[data_start + 2*i : data_start + 2*i + 2], 16)
                for i in range(messageLength)
            ]

        except (ValueError, IndexError):
            return None

        timeStamp = time.time()

        #-----------------------
        # modifyed from original
        if filterID is not None and messageID not in filterID:
            return None

        return can.Message(
            arbitration_id=messageID, 
            data=messageDataArr, 
            is_extended_id=is_extended, 
            timestamp=timeStamp
            )
        #-----------------------


    def sendCANMessage(self, message):
        if message.is_extended_id:
            prefix, id_len, max_id = 'X', 8, EXT_MAX_ID
        else:
            prefix, id_len, max_id = 'T', 3, STD_MAX_ID

        if message.arbitration_id > max_id:
            raise ValueError(f'ID 0x{message.arbitration_id:X} is too large for a '
                             f'{"29" if message.is_extended_id else "11"}-bit frame')

        idString   = f'{message.arbitration_id:0{id_len}X}'
        dataString = bytes(message.data).hex().upper()

        response = self.sendSerialMessage(f'{prefix}{idString}{len(message.data)}{dataString}')

        if response != True:
            raise ValueError('Error sending CAN message')
        else:
            return True

    def closeCANBus(self) -> bool:
        if self.device is None:
            return False
        return self.sendSerialMessage('C')

    def closeDevice(self) -> None:
        if self.device is not None:
            self.device.close()
