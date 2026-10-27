import can, time, threading
import serial, serial.serialutil

class pyCandapter:
    def __init__(self, port, baudrate = 9600) -> None:

        #Locks the thread to prevent collision
        self.lock = threading.RLock()

        try:
            self.device = serial.Serial(port=port, baudrate=baudrate, timeout=2)
            print(f"[INFO] Connected to {port} at {baudrate} baud.")
        except serial.serialutil.SerialException as e:
            print(f"[ERROR] Could not open port {port}: {e}")
            self.device = None 

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

    def sendSerialMessage(self, message) -> bool:
        with self.lock:
            self.device.write('{}\r'.format(message).encode())
            time.sleep(0.1)
            
            response = self.device.read()
            
            print(f"Sent: {message!r} | Got: {response!r} | Hex: {response.hex() if response else 'empty'}")

            if response == b'\x06':
                return True
            else:
                return False

    def readCANMessage(self,filterID=None) -> can.Message:
        with self.lock:
            message = self.device.read_until(b'\r').decode('utf-8', errors='ignore') #This is in the format Tiiilddddddddddddddd\r
            #raw = self.device.read_until(b'\r')
            #print(f"[DEBUG] raw bytes: {raw!r}")

        frame_type = message[0]  # 't', 'T', 'r', or 'R'

        id_len = 0

        if frame_type == 'T':          # Extended data frame (29-bit ID)
            is_extended = True
            id_len = 8                 # 8 hex chars = 29-bit ID
        elif frame_type == 't':        # Standard data frame (11-bit ID)
            is_extended = False
            id_len = 3                 # 3 hex chars = 11-bit ID
        else:
            return None                # RTR or unknown, handle as needed

        
        # messageID = int(message[1:4], 16)
        # messageLength = int(message[4])

        try:

            messageID     = int(message[1 : 1 + id_len], 16)
            #print(hex(messageID))
            messageLength = int(message[1 + id_len])           # DLC (0–8)

            data_start = 1 + id_len + 1
            messageDataArr = [
                int(message[data_start + 2*i : data_start + 2*i + 2], 16)
                for i in range(messageLength)
            ]

        except (ValueError, IndexError):
            return None

        # messageDataArr = []
        # for i in range(messageLength):
        #     messageDataArr.append(int(message[5 + 2*i :5 + 2*i + 2], 16))
        timeStamp = time.time()

        #-----------------------
        # modifyed from original
        CANMessage = None
        if filterID != None:
            
            if messageID in filterID:
                CANMessage = (can.Message(
                    arbitration_id=messageID, 
                    data=messageDataArr, 
                    is_extended_id=is_extended, 
                    timestamp=timeStamp
                    ))
        
        else:
            CANMessage = (can.Message(
                arbitration_id=messageID, 
                data=messageDataArr, 
                is_extended_id=is_extended, 
                timestamp=timeStamp
                ))

        
        return CANMessage
        #-----------------------


    def sendCANMessage(self, message):
        dataString = ''

        if message.is_extended_id:
            id_len = 8
        else:
            id_len = 3

        for i in range(0, len(message.data)):
            messageDataString = str(hex(message.data[i]))[2:]

            if len(messageDataString) == 1:
                messageDataString = '0' + messageDataString
            dataString += messageDataString

        messageIDString = str(hex(message.arbitration_id))[2:]

        while len(messageIDString) < 3:
            messageIDString = '0' + messageIDString
        response = self.sendSerialMessage('T{id}{length}{data}'.format(id = messageIDString, length = len(message.data), data = dataString))

        if response != True:
            raise ValueError('Error sending CAN message')
        else:
            return True

    def closeCANBus(self) -> bool:
        response = self.sendSerialMessage('C')

    def closeDevice(self) -> None:
        self.device.close()
